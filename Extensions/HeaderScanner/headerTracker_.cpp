#include "headerTracker_.hpp"

#include "contentCache_.hpp"
#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/HeaderSearch.h>
#include <llvm/Support/Path.h>

#include <boost/spirit/include/karma.hpp>
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <algorithm>
#include <memory>
#include <fstream>
#include <iostream>
#include <sstream>
#include <windows.h>

#ifndef NDEBUG
std::ofstream logging_stream( "header_log.txt" );
#endif

namespace
{
    template <typename T>
    struct PopBackGuard
    {
        PopBackGuard( T & t ) : t_( t ) {}
        ~PopBackGuard() { t_.pop_back(); }

        T & t_;
    };
}

MacroName HeaderTracker::macroForPragmaOnce( llvm::sys::fs::UniqueID const & val )
{
    std::string result;
    using namespace boost::spirit::karma;
    generate( std::back_inserter( result ),
        lit( "____pragma_once__" ) << ulong_long << lit("_") << ulong_long,
        val.getDevice(), val.getFile() );
    return MacroName( result );
}

void HeaderTracker::inclusionDirective( llvm::StringRef searchPath, llvm::StringRef relativePath, llvm::StringRef fileName, bool isAngled, clang::FileEntry const * entry )
{
    assert( !fileStack_.empty() );
    Header const & parentHeader( fileStack_.back().header );
    HeaderLocation::Enum const parentLocation( parentHeader.loc );

    // Usually after LookupFile() the resulting 'entry' is ::open()-ed. If it is
    // cached in our globalContentCache we will never read it, so its file
    // handle will be leaked. We could do ::close(), but this seems like
    // a wrong to do at this level. This is what
    // MemorizeStatCalls_PreventOpenFile is about - with it, the file is not
    // opened in LookupFile().
    // I'd prefer if Clang just allowed me to call entry->closeFD(), or better
    // yet - allowed me to disable opening the file in the first place.
    // Make sure this file is loaded through globalContentCache, so that it
    // can be shared between different SourceManager instances.
    ContentEntryPtr contentEntry = ContentCache::singleton().getOrCreate(
        preprocessor().getFileManager(), entry, cacheDisabled() ? 0 : &cache() );
    if ( !sourceManager().isFileOverridden( entry ) )
    {
        sourceManager().overrideFileContents( entry, contentEntry->buffer.get(), true );
    }
    else
    {
        assert( sourceManager().getMemoryBufferForFile( entry, 0 ) == contentEntry->buffer.get() );
    }

    bool const relativeToParent( !isAngled && ( fileStack_.back().file->getDir()->getName() == searchPath ) );

    HeaderLocation::Enum const headerLocation = relativeToParent
        // This depends on the fact that source file location is 'relative'.
        ? parentLocation 
        : preprocessor().getHeaderSearchInfo().getFileDirFlavor( entry ) == clang::SrcMgr::C_System
            ? HeaderLocation::system
            : HeaderLocation::regular
    ;

    // Only files relative to source can have an empty search path.
    assert( ( headerLocation == HeaderLocation::relative ) || !searchPath.empty() );
    // If parent is user include, this cannot be relative to source file.
    assert( ( parentLocation != HeaderLocation::regular ) || ( headerLocation != HeaderLocation::relative ) );
    // If parent is system, this must be system.
    assert( ( parentLocation != HeaderLocation::system ) || ( headerLocation == HeaderLocation::system ) );

    Dir dir;
    HeaderName headerName;

    if ( relativeToParent )
    {
        dir =  Dir( fileStack_.back().header.dir );
        llvm::StringRef const parentFilename = fileStack_.back().header.name.get();
        std::size_t const slashPos = parentFilename.find_last_of('/');
        if ( slashPos == llvm::StringRef::npos )
            headerName = HeaderName( relativePath );
        else
        {
            llvm::SmallString<512> fileName( parentFilename.data(), parentFilename.data() + slashPos + 1 );
            fileName.append( relativePath );
            headerName = HeaderName( fileName.str() );
        }
    }
    else
    {
        dir = Dir( searchPath );
        headerName = HeaderName( relativePath );
    }

    HeaderWithFileEntry const headerWithFileEntry =
    {
        {
            dir,
            headerName,
            contentEntry,
            headerLocation
        },
        entry
    };
    fileStack_.push_back( headerWithFileEntry );
}

void HeaderTracker::replaceFile( clang::FileEntry const * & entry )
{
    // Here we handle the case where header with #pragma once is included
    // implicitly, via a cache entry. In this case Clang will not skip
    // this header in usual manner, so we must cheat it to include an
    // empty file.
    // TODO: Try avoiding calling (expensive) macroForPragmaOnce() on every
    // (non-skipped) include directive.
    MacroName const pragmaOnceMacro = macroForPragmaOnce( entry->getUniqueID() );
    if ( currentHeaderCtx().getMacroValue( pragmaOnceMacro ) != undefinedMacroValue )
    {
        clang::FileEntry const * result( sourceManager().getFileManager().getVirtualFile( "__empty_file", 0, 0 ) );
        if ( !sourceManager().isFileOverridden( result ) )
            sourceManager().overrideFileContents( result, llvm::MemoryBuffer::getMemBuffer( "" ) );
        entry = result;
        replacement_ = result;
        return;
    }

    if
    (
        !cacheDisabled() &&
        ( cacheHit_ = cache().findEntry( entry->getUniqueID(), searchPathId_,
            currentHeaderCtx() ) )
    )
    {
        // There is a hit in cache!
        entry = cacheHit_->getFileEntry( sourceManager() );
        replacement_ = entry;
        std::pair<UsedCacheEntries::const_iterator, bool> const insertResult =
            usedCacheEntries_.insert( std::make_pair( entry, cacheHit_ ) );
        assert( insertResult.first->second == cacheHit_ );
    }
}

void HeaderTracker::headerSkipped()
{
    assert( !fileStack_.empty() );
    assert( hasCurrentHeaderCtx() );
    HeaderWithFileEntry const & hwf( fileStack_.back() );
    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Header skipped: '" << std::string( fileStack_.back().file->getName() ) << "'\n";
#endif

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( !cacheHit_ );

    if ( !cacheDisabled() )
    {
        clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
        clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( hwf.file ) );
        assert( !headerInfo.ControllingMacroID );
        currentHeaderCtx().macroUsed( macroForPragmaOnce( hwf.file->getUniqueID() ) );
        if ( !headerInfo.isPragmaOnce )
        {
            assert( headerInfo.ControllingMacro );
            currentHeaderCtx().macroUsed( MacroName( headerInfo.ControllingMacro->getName() ) );
        }
    }
    currentHeaderCtx().addHeader( hwf.header );
}

clang::SourceManager & HeaderTracker::sourceManager() const
{
    return preprocessor_.getSourceManager();
}

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry, llvm::StringRef fileName )
{
    assert( !hasCurrentHeaderCtx() );
    assert( mainFileEntry );
    HeaderWithFileEntry const hwf =
    {
        {
            Dir( mainFileEntry->getDir()->getName() ),
            HeaderName( llvm::sys::path::filename( fileName ) ),
            ContentEntryPtr(),
            HeaderLocation::relative
        },
        mainFileEntry
    };

    fileStack_.push_back( hwf );
#ifndef NDEBUG
    logging_stream << "Entering source file: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif

    pushHeaderCtx( 0, CacheEntryPtr() );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Entering header: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    pushHeaderCtx( replacement_, cacheHit_ );
    if ( !cacheHit_ )
        currentHeaderCtx().macroUsed( macroForPragmaOnce( fileStack_.back().file->getUniqueID() ) );
    replacement_ = 0;
    cacheHit_.reset();
}

bool HeaderTracker::isViableForCache( HeaderCtx const & headerCtx, clang::FileEntry const * file ) const
{
    // Headers which have overridden content are poor candidates for caching.
    // Currently these are cache-generated headers themselves, and empty
    // header used to implement #pragma once support.
    return headerCtx.replacement() == 0;
}

void HeaderTracker::leaveHeader()
{
    assert( currentHeaderCtx().parent() );

    assert( !fileStack_.empty() );
    clang::FileEntry const * file( fileStack_.back().file );

#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Leaving header: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

    if ( !cacheDisabled() && isViableForCache( currentHeaderCtx(), file ) )
        currentHeaderCtx().addToCache( cache(), searchPathId_, file );
    currentHeaderCtx().propagateToParent();
    popHeaderCtx();
    currentHeaderCtx().addHeader( fileStack_.back().header );
}

void HeaderCtx::addToCache( Cache & cache, std::size_t const searchPathId, clang::FileEntry const * file )
{
    assert( !cacheHit_ );
    UsedMacros usedMacros;
    usedHere_.forEachUsedMacro( [&]( UsedMacros::value_type const & macro )
    {
        usedMacros.push_back( macro );
    });
    cacheHit_ = cache.addEntry(
        file->getUniqueID(),
        searchPathId,
        std::move( usedMacros ),
        std::move( macroState_ ),
        std::move( includedHeaders_ )
    );
}

void HeaderTracker::exitSourceFile( Headers & headers )
{
#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Leaving source file: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    headers = std::move( currentHeaderCtx().includedHeaders() );
    // Undo cache overrides in source manager.
    for ( UsedCacheEntries::value_type const & entry : usedCacheEntries_ )
    {
        assert( sourceManager().isFileOverridden( entry.first ) );
        sourceManager().disableFileContentsOverride( entry.first );
    }
    // Remove ref from cache entries.
    usedCacheEntries_.clear();
    popHeaderCtx();
}

void HeaderTracker::macroUsed( llvm::StringRef name )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro used: '" << name.str() << '\'' << std::endl;
#endif
    currentHeaderCtx().macroUsed( MacroName( name ) );
}

namespace
{
    MacroValue macroValueFromDirective( clang::Preprocessor const & preprocessor, llvm::StringRef const macroName, clang::MacroDirective const * def )
    {
        assert( def );
        clang::MacroInfo const * macroInfo( def->getMacroInfo() );
        assert( macroInfo );
        assert( !macroInfo->isBuiltinMacro() );
        clang::SourceLocation const startLoc( macroInfo->getDefinitionLoc() );
        assert( !startLoc.isInvalid() );
        clang::SourceManager & sourceManager( preprocessor.getSourceManager() );
        std::pair<clang::FileID, unsigned> startSpellingLoc( sourceManager.getDecomposedSpellingLoc( startLoc ) );
        bool invalid;
        llvm::StringRef const buffer( sourceManager.getBufferData( startSpellingLoc.first, &invalid ) );
        assert( !invalid );
        char const * const macroStart = buffer.data() + startSpellingLoc.second;
        unsigned int const tokCount( macroInfo->getNumTokens() );
        llvm::StringRef result;
        if ( !tokCount )
        {
            // Macro does not have any tokens. I have no idea how to get the length
            // of the directive itself. Just go to the end of line and then back up
            // until the first character. In case we see a backslash, just ignore it
            // and keep backing up.
            char const * end = macroStart;
            while ( *end != '\n' ) ++end;
            --end;
            while ( ( *end == '\t' ) || ( *end == ' ' ) || ( *end == '\r' ) || ( *end == '\\' ) ) --end;
            result = llvm::StringRef( macroStart, end - macroStart + 1 );
        }
        else
        {
            clang::Token const & lastToken( macroInfo->getReplacementToken( tokCount - 1 ) );
            clang::SourceLocation const endLoc( lastToken.getLocation() );
            std::pair<clang::FileID, unsigned> endSpellingLoc( sourceManager.getDecomposedSpellingLoc( endLoc ) );
            endSpellingLoc.second += lastToken.getLength();
            assert( startSpellingLoc.first == endSpellingLoc.first );
            assert( startSpellingLoc.second <= endSpellingLoc.second );
            result = llvm::StringRef( macroStart, endSpellingLoc.second - startSpellingLoc.second );
        }
        // Result starts with macro name, skip that.
        return MacroValue( llvm::StringRef( result.data() + macroName.size(), result.size() - macroName.size() ) );
    }
}  // anonymous namespace

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( def->getMacroInfo()->isBuiltinMacro() )
        return;
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro defined: '" << name.str() << '\'' << std::endl;
#endif
    currentHeaderCtx().macroDefined( MacroName( name ), macroValueFromDirective( preprocessor_, name, def ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
#ifndef NDEBUG
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro undefined: '" << name.str() << '\'' << std::endl;
#endif
    currentHeaderCtx().macroUndefined( MacroName( name ) );
}

void HeaderTracker::pragmaOnce()
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    MacroName const pragmaOnceMacro( macroForPragmaOnce( fileStack_.back().file->getUniqueID() ) );
    currentHeaderCtx().macroDefined( pragmaOnceMacro, MacroValue( " 1" ) );
}

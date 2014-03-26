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
#include <iostream>
#include <sstream>

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

void HeaderTracker::inclusionDirective( llvm::StringRef searchPath, llvm::StringRef relativePath, bool isAngled, clang::FileEntry const * entry )
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
    ContentEntry const & contentEntry = ContentCache::singleton().getOrCreate(
        preprocessor().getFileManager(), entry, cacheDisabled() ? 0 : &cache() );
    if ( !sourceManager().isFileOverridden( entry ) )
    {
        sourceManager().overrideFileContents( entry, contentEntry.buffer.get(), true );
    }
    else
    {
        assert( sourceManager().getMemoryBufferForFile( entry, 0 ) == contentEntry.buffer.get() );
    }

    HeaderLocation::Enum const headerLocation = ( fileStack_.back().header.dir.get() == searchPath ) && !isAngled
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

    HeaderWithFileEntry const headerWithFileEntry =
    {
        {
            Dir( searchPath ),
            HeaderName( relativePath ),
            contentEntry.buffer.get(),
            contentEntry.checksum,
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
        currentHeaderCtx().macroUsed( pragmaOnceMacro );
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

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( !cacheHit_ );

    if ( !cacheDisabled() )
    {
        clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
        clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( hwf.file ) );
        assert( !headerInfo.ControllingMacroID );
        MacroName macroName;
        if ( headerInfo.isPragmaOnce )
        {
            macroName = macroForPragmaOnce( hwf.file->getUniqueID() );
        }
        else
        {
            assert( headerInfo.ControllingMacro );
            macroName = MacroName( headerInfo.ControllingMacro->getName() );
        }
        currentHeaderCtx().macroUsed( macroName );
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
            Dir( "" ),
            HeaderName( fileName ),
            0,
            0,
            HeaderLocation::relative
        },
        mainFileEntry
    };

    fileStack_.push_back( hwf );

    pushHeaderCtx( std::unique_ptr<HeaderCtx>( new HeaderCtx( hwf.header, 0, CacheEntryPtr(), preprocessor_ ) ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    currentHeaderCtx().addHeader( fileStack_.back().header );
    pushHeaderCtx( std::unique_ptr<HeaderCtx>( new HeaderCtx( fileStack_.back().header, replacement_, cacheHit_, preprocessor_ ) ) );
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

void HeaderTracker::leaveHeader( IgnoredHeaders const & ignoredHeaders )
{
    assert( currentHeaderCtx().parent() );

    assert( !fileStack_.empty() );
    clang::FileEntry const * file( fileStack_.back().file );

    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

    if ( !cacheDisabled() && isViableForCache( currentHeaderCtx(), file ) )
        currentHeaderCtx().addToCache( cache(), searchPathId_, file );
    currentHeaderCtx().propagateToParent( ignoredHeaders );
    popHeaderCtx();
}

void HeaderCtx::addToCache( Cache & cache, std::size_t const searchPathId, clang::FileEntry const * file )
{
    assert( !cacheHit_ );
    cacheHit_ = cache.addEntry(
        file->getUniqueID(),
        searchPathId,
        std::move( usedHere_ ),
        std::move( definedHere_ ),
        std::move( undefinedHere_ ),
        std::move( includedHeaders_ )
    );
}

void HeaderTracker::exitSourceFile( Headers & headers )
{
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

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    currentHeaderCtx().macroUsed( MacroName( name ) );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( def->getMacroInfo()->isBuiltinMacro() )
        return;
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    llvm::StringRef const macroValue( macroValueFromDirective( preprocessor_, name, def ) );
    currentHeaderCtx().macroDefined( MacroName( name ), MacroValue( macroValue ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    currentHeaderCtx().macroUndefined( MacroName( name ) );
}

void HeaderTracker::pragmaOnce()
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    MacroName const pragmaOnceMacro( macroForPragmaOnce( fileStack_.back().file->getUniqueID() ) );
    currentHeaderCtx().macroUsed( pragmaOnceMacro );
    currentHeaderCtx().macroDefined( pragmaOnceMacro, MacroValue( " 1" ) );
}

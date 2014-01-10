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

llvm::StringRef HeaderTracker::macroForPragmaOnce( llvm::sys::fs::UniqueID const & val )
{
    std::string result;
    using namespace boost::spirit::karma;
    generate( std::back_inserter( result ),
        lit( "____pragma_once__" ) << ulong_long << lit("_") << ulong_long,
        val.getDevice(), val.getFile() );
    return *tmpStrings_.insert( result ).first;
}

void HeaderTracker::inclusionDirective( llvm::StringRef searchPath, llvm::StringRef relativePath, bool isAngled, clang::FileEntry const * entry )
{
    assert( !fileStack_.empty() );
    Header const & parentHeader( fileStack_.back().header );
    clang::FileEntry const * parentFile = fileStack_.back().file;
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
            preprocessor().getFileManager(), entry, cache() );
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
    clang::HeaderSearch & hs( preprocessor().getHeaderSearchInfo() );
    clang::HeaderSearch const & cHs( hs );
    // Here we handle the case where header with #pragma once is included
    // implicitly, via a cache entry. In this case Clang will not skip
    // this header in usual manner, so we must cheat it to include an
    // empty file.
    // TODO: Try avoiding calling (expensive) macroForPragmaOnce() on every
    // (non-skipped) include directive.
    llvm::StringRef const pragmaOnceMacro = macroForPragmaOnce( entry->getUniqueID() );
    if ( headerCtxStack().back().getMacroValue( pragmaOnceMacro ) != undefinedMacroValue() )
    {
        headerCtxStack().back().macroUsed( pragmaOnceMacro );
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
            headerCtxStack().back() ) )
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
    assert( !headerCtxStack().empty() );
    HeaderWithFileEntry const & hwf( fileStack_.back() );
    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( !cacheHit_ );
    if ( headerCtxStack().empty() )
        return;

    if ( !cacheDisabled() )
    {
        clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
        clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( hwf.file ) );
        assert( !headerInfo.ControllingMacroID );
        llvm::StringRef macroName;
        if ( headerInfo.isPragmaOnce )
        {
            macroName = macroForPragmaOnce( hwf.file->getUniqueID() );
        }
        else
        {
            assert( headerInfo.ControllingMacro );
            macroName = headerInfo.ControllingMacro->getName();
        }
        headerCtxStack().back().macroUsed( macroName );
    }
    headerCtxStack().back().addHeader( hwf.header );
}

clang::SourceManager & HeaderTracker::sourceManager() const
{
    return preprocessor_.getSourceManager();
}

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry, llvm::StringRef fileName )
{
    assert( headerCtxStack().empty() );
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

    headerCtxStack().push_back( HeaderCtx( hwf.header, 0, CacheEntryPtr(), preprocessor_, 0 ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    headerCtxStack().back().addHeader( fileStack_.back().header );
    headerCtxStack().push_back( HeaderCtx( fileStack_.back().header, replacement_, cacheHit_, preprocessor_, &headerCtxStack().back() ) );
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
    assert( headerCtxStack().size() > 1 );

    assert( !fileStack_.empty() );
    clang::FileEntry const * file( fileStack_.back().file );

    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );
    PopBackGuard<HeaderCtxStack> const popHeaderCtxStack( headerCtxStack_ );

    HeaderCtxStack::size_type const stackSize( headerCtxStack().size() );
    if ( cacheDisabled() )
        return;

    if ( isViableForCache( headerCtxStack().back(), file ) )
        headerCtxStack().back().addToCache( cache(), searchPathId_, file );
    headerCtxStack().back().propagateToParent( ignoredHeaders );
}


CacheEntryPtr HeaderCtx::addToCache( Cache & cache, std::size_t const searchPathId, clang::FileEntry const * file ) const
{
    return cache.addEntry( file->getUniqueID(), searchPathId, createCacheKey(), createHeaderContent(), includedHeaders() );
}

Headers HeaderTracker::exitSourceFile()
{
    PopBackGuard<HeaderCtxStack> const popHeaderCtxStack( headerCtxStack() );
    Headers result;
    result.swap( headerCtxStack().back().includedHeaders() );
    // Undo cache overrides in source manager.
    for ( UsedCacheEntries::value_type const & entry : usedCacheEntries_ )
    {
        assert( sourceManager().isFileOverridden( entry.first ) );
        sourceManager().disableFileContentsOverride( entry.first );
    }
    // Remove ref from cache entries.
    usedCacheEntries_.clear();
    return result;
}

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * )
{
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroUsed( name );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( def->getMacroInfo()->isBuiltinMacro() )
        return;
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    llvm::StringRef const macroValue( macroValueFromDirective( preprocessor_, name, def ) );
    headerCtxStack().back().macroDefined( name, macroValue );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroUndefined( name );
}

void HeaderTracker::pragmaOnce()
{
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    llvm::StringRef const pragmaOnceMacro( macroForPragmaOnce( fileStack_.back().file->getUniqueID() ) );
    headerCtxStack().back().macroUsed( pragmaOnceMacro );
    headerCtxStack().back().macroDefined( pragmaOnceMacro, " 1" );
}

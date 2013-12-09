#include "headerTracker_.hpp"

#include "contentCache_.hpp"
#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/HeaderSearch.h>
#include <llvm/Support/Path.h>

#include <boost/spirit/include/karma.hpp>
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <unordered_map>
#include <algorithm>
#include <iostream>
#include <sstream>

namespace
{
    #define BASE 65521UL
    #define NMAX 5552

    #define DO1(buf, i) { sum1 += (buf)[i]; sum2 += sum1; }
    #define DO2(buf, i) DO1(buf, i); DO1(buf, i + 1);
    #define DO4(buf, i) DO2(buf, i); DO2(buf, i + 2);
    #define DO8(buf, i) DO4(buf, i); DO4(buf, i + 4);
    #define DO16(buf) DO8(buf, 0); DO8(buf, 8);
    #define MOD(a) a %= BASE

    std::size_t bsc_adler32( char const * data, std::size_t size )
    {
        unsigned int sum1 = 1;
        unsigned int sum2 = 0;

        while (size >= NMAX)
        {
            for (int i = 0; i < NMAX / 16; ++i)
            {
                DO16(data); data += 16;
            }
            MOD(sum1); MOD(sum2); size -= NMAX;
        }

        while (size >= 16)
        {
            DO16(data); data += 16; size -= 16;
        }

        while (size > 0)
        {
            DO1(data, 0); data += 1; size -= 1;
        }

        MOD(sum1); MOD(sum2);

        return sum1 | (sum2 << 16);
    }


    ////////////////////////////////////////////////////////////////////////////
    //
    // adler32()
    // ---------
    //
    ////////////////////////////////////////////////////////////////////////////

    std::size_t adler32( llvm::MemoryBuffer const * buffer )
    {
        return bsc_adler32( buffer->getBufferStart(), buffer->getBufferSize() );
    }
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
    llvm::MemoryBuffer const * buffer;
    // Make sure this file is loaded through globalContentCache, so that it
    // can be shared between different SourceManager instances.
    if ( !sourceManager().isFileOverridden( entry ) )
    {
        buffer = ContentCache::singleton().getOrCreate(
            preprocessor().getFileManager(), entry );
        sourceManager().overrideFileContents( entry, buffer, true );
    }
    else
    {
        buffer = sourceManager().getMemoryBufferForFile( entry, 0 );
#ifndef NDEBUG
        llvm::MemoryBuffer const * gccBuf = ContentCache::singleton().get( entry->getUniqueID() );
        assert( buffer == gccBuf );
#endif
    }

    HeaderLocation::Enum const headerLocation = ( fileStack_.back().header.dir.get() == searchPath ) && !isAngled
        // This depends on the fact that source file location is 'relative'.
        ? parentLocation 
        : preprocessor().getHeaderSearchInfo().getFileDirFlavor( entry ) == clang::SrcMgr::C_System
            ? HeaderLocation::system
            : HeaderLocation::regular
    ;

    // If parent is user include, this cannot be relative to source file.
    assert( ( parentLocation != HeaderLocation::regular ) || ( headerLocation != HeaderLocation::relative ) );
    // If parent is system, this must be system.
    assert( ( parentLocation != HeaderLocation::system ) || ( headerLocation == HeaderLocation::system ) );

    HeaderWithFileEntry const headerWithFileEntry =
    {
        {
            fromStringRef<Dir>( searchPath ),
            fromStringRef<HeaderName>( relativePath ),
            buffer,
            adler32( buffer ),
            headerLocation
        },
        entry
    };
    fileStack_.push_back( headerWithFileEntry );
}

void HeaderTracker::replaceFile( clang::FileEntry const * & entry )
{
    if
    (
        !cacheDisabled() &&
        ( cacheHit_ = cache().findEntry( entry->getUniqueID(), headerCtxStack().back() ) )
    )
    {
        // There is a hit in cache!
        entry = cacheHit_->getFileEntry( preprocessor().getSourceManager() );
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
    fileStack_.pop_back();

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( !cacheHit_ );
    if ( !headerCtxStack().empty() )
    {
        if ( !cacheDisabled() )
        {
            clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
            clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( hwf.file ) );
            assert( !headerInfo.isImport );
            assert( !headerInfo.ControllingMacroID );
            assert( !headerInfo.isPragmaOnce );
            assert( headerInfo.ControllingMacro );
            clang::MacroDirective const * directive( preprocessor().getMacroDirectiveHistory( headerInfo.ControllingMacro ) );
            assert( directive );

            llvm::StringRef const & macroName( headerInfo.ControllingMacro->getName() );
            headerCtxStack().back().macroUsed( macroName );
        }
        headerCtxStack().back().addHeader( hwf.header );
    }
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
            fromStringRef<Dir>( llvm::StringRef() ),
            fromStringRef<HeaderName>( fileName ),
            0,
            0,
            HeaderLocation::relative
        },
        mainFileEntry
    };

    fileStack_.push_back( hwf );
    headerCtxStack().push_back( HeaderCtx( hwf.header, CacheEntryPtr(), preprocessor_, 0 ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    headerCtxStack().back().addHeader( fileStack_.back().header );
    headerCtxStack().push_back( HeaderCtx( fileStack_.back().header, cacheHit_, preprocessor_, &headerCtxStack().back() ) );
    cacheHit_.reset();
}

bool HeaderTracker::isViableForCache( HeaderCtx const & headerCtx, clang::FileEntry const * file ) const
{
    return true;
}

void HeaderTracker::leaveHeader( IgnoredHeaders const & ignoredHeaders )
{
    assert( headerCtxStack().size() > 1 );

    assert( !fileStack_.empty() );
    clang::FileEntry const * file( fileStack_.back().file );
    fileStack_.pop_back();
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        Cleanup( HeaderCtxStack & stack ) : stack_( stack ) {}
        ~Cleanup() { stack_.pop_back(); }
    } const cleanup( headerCtxStack() );

    HeaderCtxStack::size_type const stackSize( headerCtxStack().size() );
    // Propagate the results to the file which included us.
    CacheEntryPtr cacheEntry;
    if ( !cacheDisabled() && !headerCtxStack().back().fromCache() && isViableForCache( headerCtxStack().back(), file ) )
        cacheEntry = headerCtxStack().back().addToCache( cache(), file );
    else
        cacheEntry = headerCtxStack().back().cacheHit();
    headerCtxStack().back().propagateToParent( ignoredHeaders, cacheEntry );
}


CacheEntryPtr HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file ) const
{
    return cache.addEntry( file->getUniqueID(), createCacheKey(), createHeaderContent(), includedHeaders() );
}

Headers HeaderTracker::exitSourceFile()
{
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        Cleanup( HeaderCtxStack & stack ) : stack_( stack ) {}
        ~Cleanup() { stack_.pop_back(); }
    } const cleanup( headerCtxStack() );

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

#include "headerTracker_.hpp"

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
    class ContentCache
    {
    public:
        typedef std::unordered_map<std::string, llvm::MemoryBuffer const *> ContentMap;
    
        ~ContentCache()
        {
            for ( auto & value : contentMap_ )
                delete value.second;
        }

        llvm::MemoryBuffer const * get( llvm::StringRef name ) const
        {
            boost::shared_lock<boost::shared_mutex> const readLock( contentMutex_ );
            ContentMap::const_iterator const iter( contentMap_.find( name ) );
            return iter != contentMap_.end() ? iter->second : 0;
        }

        llvm::MemoryBuffer const * getOrCreate( clang::FileManager & fm, clang::FileEntry const * file )
        {
            llvm::MemoryBuffer const * buffer( get( file->getName() ) );
            if ( buffer )
                return buffer;
            buffer = fm.getBufferForFile( file );
            boost::unique_lock<boost::shared_mutex> const writeLock( contentMutex_ );
            contentMap_.insert( std::make_pair( file->getName(), buffer ) );
            return buffer;
        }

    private:
        mutable boost::shared_mutex contentMutex_;
        ContentMap contentMap_;
    } globalContentCache;
}

void HeaderTracker::findFile( llvm::StringRef include, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    assert( !fileStack_.empty() );
    Header const & parentHeader( fileStack_.back().header );
    clang::FileEntry const * parentFile = fileStack_.back().file;
    clang::DirectoryLookup const * dirLookup( 0 );
    HeaderLocation::Enum const parentLocation( parentHeader.loc );
    Dir const & parentSearchPath = parentHeader.dir;
    HeaderName const & parentRelative = parentHeader.name;

    llvm::SmallString<1024> searchPath;
    llvm::SmallString<1024> relativePath;

    clang::FileEntry const * entry = headerSearch_->LookupFile( include, isAngled, 0, dirLookup, parentFile, &searchPath, &relativePath, 0, false );
    if ( !entry )
        return;

    // Make sure this file is loaded through globalContentCache, so that it
    // can be shared between different SourceManager instances.
    llvm::MemoryBuffer const * buffer( globalContentCache.getOrCreate(
        preprocessor().getFileManager(), entry ) );
    sourceManager().overrideFileContents( entry, buffer, true );

    HeaderLocation::Enum const headerLocation = dirLookup == 0
        ? fileStack_.size() == 1
            ? HeaderLocation::relative
            : parentLocation
        : headerSearch_->getFileDirFlavor( entry ) == clang::SrcMgr::C_System
            ? HeaderLocation::system
            : HeaderLocation::regular
    ;

    // If including header is system header, then so are we.
    assert( ( parentLocation != HeaderLocation::system ) || ( headerLocation == HeaderLocation::system ) );

    if ( headerLocation == HeaderLocation::relative )
    {
        searchPath = parentSearchPath.get();
        relativePath = parentRelative.get();
        llvm::sys::path::remove_filename( relativePath );
        llvm::sys::path::append( relativePath, include );
    }

    HeaderWithFileEntry const headerWithFileEntry =
    {
        {
            fromStringRef<Dir>( searchPath ),
            fromStringRef<HeaderName>( relativePath ),
            buffer,
            headerLocation
        },
        entry
    };
    fileStack_.push_back( headerWithFileEntry );

    if
    (
        !cacheDisabled() &&
        headerSearch_->ShouldEnterIncludeFile( entry, false ) &&
        ( cacheHit_ = cache().findEntry( entry->getName(), headerCtxStack().back() ) )
    )
    {
        // There is a hit in cache!
        fileEntry = cacheHit_->getFileEntry( preprocessor().getSourceManager() );
    }
    else
    {
        // No match in cache. We will have to use the disk file.
        fileEntry = entry;
    }
}

void HeaderTracker::headerSkipped()
{
    assert( !fileStack_.empty() );
    assert( !headerCtxStack().empty() );
    HeaderWithFileEntry const hwf( fileStack_.back() );
    fileStack_.pop_back();

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( cacheHit_ == 0 );
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

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry, llvm::StringRef dir, llvm::StringRef relFilename )
{
    assert( headerCtxStack().empty() );
    assert( mainFileEntry );
    HeaderWithFileEntry const hwf =
    {
        {
            fromStringRef<Dir>( dir ),
            fromStringRef<HeaderName>( relFilename ),
            0,
            HeaderLocation::regular
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
    return cache.addEntry( file->getName(), createCacheKey(), createHeaderContent(), includedHeaders() );
}

Preprocessor::HeaderRefs HeaderTracker::exitSourceFile()
{
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        Cleanup( HeaderCtxStack & stack ) : stack_( stack ) {}
        ~Cleanup() { stack_.pop_back(); }
    } const cleanup( headerCtxStack() );

    Preprocessor::HeaderRefs result;
    std::for_each(
        headerCtxStack().back().includedHeaders().begin(),
        headerCtxStack().back().includedHeaders().end(),
        [&]( Header const & h )
        {
            assert( h.buffer );
            result.insert(
                HeaderRef(
                    h.dir.get(),
                    h.name.get(),
                    h.loc,
                    h.buffer->getBufferStart(),
                    h.buffer->getBufferSize() ) );
        }
    );
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

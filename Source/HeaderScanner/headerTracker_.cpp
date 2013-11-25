#include "headerTracker_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/HeaderSearch.h>
#include <llvm/Support/Path.h>

#include <boost/spirit/include/karma.hpp>

#include <algorithm>
#include <iostream>
#include <sstream>

void HeaderTracker::findFile( llvm::StringRef include, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    assert( !fileStack_.empty() );
    Header const & parentHeader( fileStack_.back() );
    clang::FileEntry const * parentFile = parentHeader.file;
    clang::DirectoryLookup const * dirLookup( 0 );
    HeaderLocation::Enum const parentLocation( parentHeader.loc );
    Dir const & parentSearchPath = parentHeader.dir;
    HeaderName const & parentRelative = parentHeader.name;

    llvm::SmallString<1024> searchPath;
    llvm::SmallString<1024> relativePath;

    clang::FileEntry const * entry = headerSearch_->LookupFile( include, isAngled, 0, dirLookup, parentFile, &searchPath, &relativePath, 0, false );
    if ( !entry )
        return;

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

    Header const header =
    {
        fromStringRef<Dir>( searchPath ),
        fromStringRef<HeaderName>( relativePath ),
        entry,
        headerLocation
    };
    fileStack_.push_back( header );

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
    Header const header( fileStack_.back() );
    fileStack_.pop_back();

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( header.file ) );
    assert( cacheHit_ == 0 );
    if ( !headerCtxStack().empty() )
    {
        if ( !cacheDisabled() )
        {
            clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
            clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( header.file ) );
            assert( !headerInfo.isImport );
            assert( !headerInfo.ControllingMacroID );
            assert( !headerInfo.isPragmaOnce );
            assert( headerInfo.ControllingMacro );
            clang::MacroDirective const * directive( preprocessor().getMacroDirectiveHistory( headerInfo.ControllingMacro ) );
            assert( directive );

            llvm::StringRef const & macroName( headerInfo.ControllingMacro->getName() );
            headerCtxStack().back().macroUsed( macroName );
        }
        headerCtxStack().back().addHeader( header );
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
    Header const header =
    {
        fromStringRef<Dir>( dir ),
        fromStringRef<HeaderName>( relFilename ),
        mainFileEntry,
        HeaderLocation::regular
    };

    fileStack_.push_back( header );
    headerCtxStack().push_back( HeaderCtx( header, CacheEntryPtr(), preprocessor_, 0 ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    headerCtxStack().back().addHeader( fileStack_.back() );
    headerCtxStack().push_back( HeaderCtx( fileStack_.back(), cacheHit_, preprocessor_, &headerCtxStack().back() ) );
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
            std::string error;
            bool invalid;
            llvm::MemoryBuffer const * buffer = sourceManager().getMemoryBufferForFile( h.file, &invalid );
            assert( buffer );
            result.insert(
                HeaderRef(
                    h.dir.get(),
                    h.name.get(),
                    h.loc,
                    buffer->getBufferStart(),
                    buffer->getBufferSize() ) );
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

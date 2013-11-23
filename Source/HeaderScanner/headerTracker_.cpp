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
    IncludeStackEntry currentEntry( fileStack_.back() );
    clang::FileEntry const * currentFile = std::get<0>( currentEntry );
    clang::DirectoryLookup const * dirLookup( 0 );
    HeaderLocation::Enum const parentLocation( std::get<1>( currentEntry ) );
    PathPart const & parentSearchPath = std::get<2>( currentEntry );
    PathPart const & parentRelative = std::get<3>( currentEntry );

    PathPart searchPath;
    PathPart relativePath;

    clang::FileEntry const * entry = headerSearch_->LookupFile( include, isAngled, 0, dirLookup, currentFile, &searchPath, &relativePath, 0, false );
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
        searchPath = parentSearchPath;
        relativePath = parentRelative;
        llvm::sys::path::remove_filename( relativePath );
        llvm::sys::path::append( relativePath, include );
    }

    fileStack_.push_back( std::make_tuple( entry, headerLocation, searchPath, relativePath ) );

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
    IncludeStackEntry const & currentEntry( fileStack_.back() );
    clang::FileEntry const * file( std::get<0>( currentEntry ) );
    HeaderLocation::Enum const headerLocation( std::get<1>( currentEntry ) );
    PathPart const & dirPart( std::get<2>( currentEntry ) );
    PathPart const & relPart( std::get<3>( currentEntry ) );
    fileStack_.pop_back();

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( file ) );
    assert( cacheHit_ == 0 );
    if ( !headerCtxStack().empty() )
    {
        if ( !cacheDisabled() )
        {
            clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
            clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( file ) );
            assert( !headerInfo.isImport );
            assert( !headerInfo.ControllingMacroID );
            assert( !headerInfo.isPragmaOnce );
            assert( headerInfo.ControllingMacro );
            clang::MacroDirective const * directive( preprocessor().getMacroDirectiveHistory( headerInfo.ControllingMacro ) );
            assert( directive );

            llvm::StringRef const & macroName( headerInfo.ControllingMacro->getName() );
            headerCtxStack().back().macroUsed( macroName );
        }
        headerCtxStack().back().addHeader
        ( Header( std::make_tuple(
            fromDataAndSize<Dir>( dirPart.data(), dirPart.size() ),
            fromDataAndSize<HeaderName>( relPart.data(), relPart.size() ),
            file, headerLocation ) ) );
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
    headerCtxStack().push_back(
        HeaderCtx( std::make_tuple(
            fromDataAndSize<Dir>( dir.data(), dir.size() ),
            fromDataAndSize<HeaderName>( relFilename.data(), relFilename.size() ),
            mainFileEntry, HeaderLocation::regular ), CacheEntryPtr(), preprocessor_, 0 ) );
    PathPart dirPart( dir.data(), dir.data() + dir.size() );
    PathPart relPart( relFilename.data(), relFilename.data() + relFilename.size() );
    fileStack_.push_back( std::make_tuple( mainFileEntry, HeaderLocation::regular, dirPart, relPart ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    IncludeStackEntry const & currentEntry( fileStack_.back() );
    clang::FileEntry const * file( std::get<0>( currentEntry ) );
    HeaderLocation::Enum const headerLocation( std::get<1>( currentEntry ) );
    PathPart const & dirPart( std::get<2>( currentEntry ) );
    PathPart const & relPart( std::get<3>( currentEntry ) );
    Header header( std::make_tuple(
        fromDataAndSize<Dir>( dirPart.data(), dirPart.size() ),
        fromDataAndSize<HeaderName>( relPart.data(), relPart.size() ),
        file, headerLocation ) );
    headerCtxStack().back().addHeader( header );
    headerCtxStack().push_back( HeaderCtx( header, cacheHit_, preprocessor_, &headerCtxStack().back() ) );
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
    IncludeStackEntry const & currentEntry( fileStack_.back() );
    clang::FileEntry const * file( std::get<0>( currentEntry ) );
    fileStack_.pop_back();
    assert( file );
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
        cacheEntry = headerCtxStack().back().addToCache( cache(), file, sourceManager() );
    else
        cacheEntry = headerCtxStack().back().cacheHit();
    headerCtxStack().back().propagateToParent( ignoredHeaders, cacheEntry );
}


CacheEntryPtr HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file, clang::SourceManager & sourceManager ) const
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
            clang::FileEntry const * headerFile( std::get<2>( h ) );
            assert( headerFile );
            llvm::MemoryBuffer const * buffer = sourceManager().getMemoryBufferForFile( headerFile, &invalid );
            assert( buffer );
            result.insert(
                HeaderRef(
                    std::get<0>( h ).get(),
                    std::get<1>( h ).get(),
                    std::get<3>( h ),
                    buffer->getBufferStart(),
                    buffer->getBufferSize() ) );
        } );
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

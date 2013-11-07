#include "headerTracker_.hpp"

#include "utility_.hpp"

#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/HeaderSearch.h"
#include "llvm/Support/Path.h"

#include <algorithm>
#include <iostream>
#include <sstream>

void HeaderTracker::findFile( llvm::StringRef include, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    // Find the actual file being used.
    assert( !fileStack_.empty() );
    IncludeStackEntry currentEntry( fileStack_.back() );
    clang::FileEntry const * currentFile = std::get<0>( currentEntry );
    clang::DirectoryLookup const * curDir( 0 );
    HeaderLocation::Enum const parentLocation( std::get<1>( currentEntry ) );
    HeaderLocation::Enum headerLocation;

    PathPart searchPath;
    PathPart relativePath;

    // If including header is system header, then so are we.
    if ( parentLocation == HeaderLocation::system )
    {
        assert( fileStack_.size() > 1 );
        headerLocation = HeaderLocation::system;
    }

    clang::HeaderSearch * headerSearch;

    PathPart const & parentSearchPath = std::get<2>( currentEntry );
    PathPart const & parentRelative = std::get<3>( currentEntry );

    clang::FileEntry const * entry( 0 );
    if ( !isAngled && fileStack_.size() == 1 )
    {
        entry = relativeHeaderSearch_->LookupFile( include, false, 0, curDir, currentFile, &searchPath, &relativePath, 0, false );
        if ( entry )
        {
            headerLocation = HeaderLocation::relative;
            headerSearch = relativeHeaderSearch_.get();
        }
    }

    if ( !entry )
    {
        entry = userHeaderSearch_->LookupFile( include, isAngled, 0, curDir, currentFile, &searchPath, &relativePath, 0, false );
        if ( entry )
        {
            headerLocation = HeaderLocation::regular;
            headerSearch = userHeaderSearch_.get();
        }
    }

    if ( !entry )
    {
        entry = systemHeaderSearch_->LookupFile( include, isAngled, 0, curDir, currentFile, &searchPath, &relativePath, 0, false );
        if ( entry )
        {
            headerLocation = HeaderLocation::system;
            headerSearch = systemHeaderSearch_.get();
        }
    }

    if ( !entry )
        return;

    if ( headerLocation == HeaderLocation::relative )
    {
        searchPath = parentSearchPath;
        relativePath = parentRelative;
        llvm::sys::path::remove_filename( relativePath );
        llvm::sys::path::append( relativePath, include );
    }

    fileStack_.push_back( std::make_tuple( entry, headerLocation, searchPath, relativePath ) );
    if ( cacheDisabled() || !headerSearch->ShouldEnterIncludeFile( entry, false ) )
    {
        // File will be skipped anyway. Do not search cache.
        fileEntry = entry;
        return;
    }

    CacheEntryPtr const cacheHit( cache().findEntry( entry->getName(), macroState() ) );
    if ( !cacheHit )
    {
        fileEntry = entry;
        return;
    }
    cacheHit_ = cacheHit;
    fileEntry = cacheHit->getFileEntry( preprocessor().getSourceManager() );
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
            headerCtxStack().back().macroUsed( macroName, macroState() );
        }
        HeaderFile header( std::make_tuple(
            fromDataAndSize<Dir>( dirPart.data(), dirPart.size() ),
            fromDataAndSize<HeaderName>( relPart.data(), relPart.size() ),
            file, headerLocation ) );
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
    headerCtxStack().push_back(
        HeaderCtx( std::make_tuple(
            fromDataAndSize<Dir>( dir.data(), dir.size() ),
            fromDataAndSize<HeaderName>( relFilename.data(), relFilename.size() ),
            mainFileEntry, HeaderLocation::regular ), CacheEntryPtr(), preprocessor_ ) );
    PathPart dirPart( dir.data(), dir.data() + dir.size() );
    PathPart relPart( relFilename.data(), relFilename.data() + relFilename.size() );
    fileStack_.push_back( std::make_tuple( mainFileEntry, HeaderLocation::regular, dirPart, relPart ) );
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
    IncludeStackEntry const & currentEntry( fileStack_.back() );
    clang::FileEntry const * file( std::get<0>( currentEntry ) );
    assert( file );
    HeaderLocation::Enum const headerLocation( std::get<1>( currentEntry ) );
    PathPart const & dirPart( std::get<2>( currentEntry ) );
    PathPart const & relPart( std::get<3>( currentEntry ) );
    HeaderFile header( std::make_tuple(
        fromDataAndSize<Dir>( dirPart.data(), dirPart.size() ),
        fromDataAndSize<HeaderName>( relPart.data(), relPart.size() ),
        file, headerLocation ) );
    if ( file )
    {
        headerCtxStack().back().addHeader( header );
        headerCtxStack().push_back( HeaderCtx( header, cacheHit_, preprocessor_ ) );
        cacheHit_.reset();
    }
}

void HeaderTracker::leaveHeader( PreprocessingContext::IgnoredHeaders const & ignoredHeaders )
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

    // Sometimes we do not want to propagate headers upwards. More specifically,
    // if we are in a PCH source header, headers it includes are not needed as
    // their contents is a part of the PCH file.
    bool const ignoreHeaders
    (
        ignoredHeaders.find( std::get<0>( headerCtxStack().back().header() ) ) != ignoredHeaders.end()
    );

    CacheEntryPtr cacheEntry;

    if ( !cacheDisabled() )
    {
        cacheEntry = headerCtxStack().back().cacheHit();
        if ( !cacheEntry )
            cacheEntry = headerCtxStack().back().addToCache( cache(), file, sourceManager() );
    }

    HeaderCtx & includer( headerCtxStack()[ stackSize - 2 ] );
    if ( cacheEntry )
    {
        includer.addStuff( cacheEntry, ignoreHeaders );
    }
    else if ( !ignoreHeaders )
    {
        includer.addHeaders( headerCtxStack().back().includedHeaders() );
    }
}


CacheEntryPtr HeaderTracker::HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file, clang::SourceManager & sourceManager ) const
{
    return cache.addEntry( file, usedMacros(), headerContent(), includedHeaders() );
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
    struct Inserter
    {
        typedef void result_type;
        Inserter( Preprocessor::HeaderRefs & result, clang::SourceManager & sourceManager )
            : result_( result ), sourceManager_( sourceManager ) {}

        void operator()( HeaderFile const & h )
        {
            std::string error;
            bool invalid;
            clang::FileEntry const * headerFile( std::get<2>( h ) );
            assert( headerFile );
            llvm::MemoryBuffer const * buffer = sourceManager_.getMemoryBufferForFile( headerFile, &invalid );
            if ( invalid )
                buffer = sourceManager_.getFileManager().getBufferForFile( headerFile, &error );
            assert( buffer );
            result_.insert(
                HeaderRef(
                    std::get<0>( h ).get(),
                    std::get<1>( h ).get(),
                    std::get<3>( h ),
                    buffer->getBufferStart(),
                    buffer->getBufferSize() ) );
        }
        void operator()( CacheEntryPtr const & ce )
        {
            std::for_each( ce->headers().begin(), ce->headers().end(),
                [this]( Header const & h ) { boost::apply_visitor( *this, h ); } );
        }
        Preprocessor::HeaderRefs & result_;
        clang::SourceManager & sourceManager_;
    } inserter( result, preprocessor_.getSourceManager() );
    std::for_each(
        headerCtxStack().back().includedHeaders().begin(),
        headerCtxStack().back().includedHeaders().end(),
        [&]( Header const & h ) { boost::apply_visitor( inserter, h ); } );
    return result;
}

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * )
{
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroUsed( name, macroState() );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( def->getMacroInfo()->isBuiltinMacro() )
        return;
    llvm::StringRef const macroValue( macroValueFromDirective( preprocessor_, name, def ) );
    macroState().defineMacro( name, macroValue );
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroDefined( name, macroValue );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    macroState().undefineMacro( name );
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroUndefined( name );
}

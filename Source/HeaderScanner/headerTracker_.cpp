#include "headerTracker_.hpp"

#include "utility_.hpp"

#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/HeaderSearch.h"

#include <algorithm>
#include <iostream>
#include <sstream>

void HeaderTracker::findFile( llvm::StringRef relative, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    // Find the actual file being used.
    assert( !fileStack_.empty() );
    clang::FileEntry const * currentFile( fileStack_.back() );
    clang::DirectoryLookup const * dontCare;
    clang::FileEntry const * entry = headerSearch_->LookupFile( relative, isAngled, 0, dontCare, currentFile, 0, 0, 0, false );
    if ( !entry )
        return;

    fileStack_.push_back( entry );
    if ( cacheDisabled() || !headerSearch_->ShouldEnterIncludeFile( entry, false ) )
    {
        // File will be skipped anyway. Do not search cache.
        fileEntry = entry;
        return;
    }

    std::shared_ptr<Cache::CacheEntry> const cacheHit( cache().findEntry( entry->getName(), preprocessor() ) );
    if ( !cacheHit )
    {
        fileEntry = entry;
        return;
    }
    cacheHit_ = cacheHit;
    cacheEntriesUsed_.push_back( cacheHit );
    fileEntry = cacheHit->getFileEntry( preprocessor().getSourceManager() );
}

void HeaderTracker::headerSkipped( llvm::StringRef const relative )
{
    clang::FileEntry const * file( fileStack_.back() );
    fileStack_.pop_back();
    assert( file );

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( file ) );
    assert( cacheHit_ == 0 );
    HeaderName header( std::make_pair( relative, file ) );
    if ( !headerCtxStack().empty() )
    {
        if ( !cacheDisabled() )
        {
            clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
            clang::HeaderFileInfo const & headerInfo( headerSearch.getFileInfo( file ) );
            assert( !headerInfo.isImport );
            assert( !headerInfo.ControllingMacroID );
            assert( !headerInfo.isPragmaOnce );
            if ( headerInfo.ControllingMacro )
            {
                clang::MacroDirective const * directive( preprocessor().getMacroDirectiveHistory( headerInfo.ControllingMacro ) );
                assert( directive );

                headerCtxStack().back().macroUsed
                (
                    std::make_pair
                    (
                        headerInfo.ControllingMacro->getName(),
                        macroDefFromSourceLocation( directive )
                    )
                );
            }
        }
        headerCtxStack().back().addHeader( header );
    }
}

clang::SourceManager & HeaderTracker::sourceManager() const
{
    return preprocessor_.getSourceManager();
}

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry )
{
    assert( headerCtxStack().empty() );
    assert( mainFileEntry );
    headerCtxStack().push_back( HeaderCtx( std::make_pair( "<<<MAIN FILE>>>", mainFileEntry ), std::shared_ptr<Cache::CacheEntry>() ) );
    fileStack_.push_back( mainFileEntry );
}

void HeaderTracker::enterHeader( llvm::StringRef relative )
{
    clang::FileEntry const * file( fileStack_.back() );
    if ( file )
    {
        HeaderName header( std::make_pair( relative, file ) );
        headerCtxStack().back().addHeader( header );
        headerCtxStack().push_back( HeaderCtx( header, cacheHit_ ) );
        cacheHit_.reset();
    }
}

void HeaderTracker::leaveHeader( PreprocessingContext::IgnoredHeaders const & ignoredHeaders )
{
    assert( headerCtxStack().size() > 1 );

    clang::FileEntry const * file( fileStack_.back() );
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
    bool const ignoreHeaders( ignoredHeaders.find( headerCtxStack().back().header().first ) != ignoredHeaders.end() );

    std::shared_ptr<Cache::CacheEntry> cacheEntry;

    if ( !cacheDisabled() )
    {
        cacheEntry = headerCtxStack().back().cacheHit();
        if ( !cacheEntry )
            cacheEntry = headerCtxStack().back().addToCache( cache(), file, sourceManager() );
    }

    HeaderCtx & includer( headerCtxStack()[ stackSize - 2 ] );
    includer.addStuff( cacheEntry, ignoreHeaders ? 0 : &headerCtxStack().back().includedHeaders() );
}


std::shared_ptr<Cache::CacheEntry> HeaderTracker::HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file, clang::SourceManager & sourceManager ) const
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

    cacheEntriesUsed_.clear();
    Preprocessor::HeaderRefs result;
    struct Inserter
    {
        typedef void result_type;
        Inserter( Preprocessor::HeaderRefs & result, clang::SourceManager & sourceManager )
            : result_( result ), sourceManager_( sourceManager ) {}

        void operator()( HeaderName const & sp )
        {
            std::string error;
            bool invalid;
            llvm::MemoryBuffer const * buffer = sourceManager_.getMemoryBufferForFile( sp.second, &invalid );
            if ( invalid )
                buffer = sourceManager_.getFileManager().getBufferForFile( sp.second, &error );
            assert( buffer );
            result_.insert( HeaderRef( sp.first, buffer->getBufferStart(), buffer->getBufferSize() ) );
        }
        void operator()( std::shared_ptr<Cache::CacheEntry> const & ce )
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

llvm::StringRef HeaderTracker::macroDefFromSourceLocation( clang::MacroDirective const * def )
{
    return ::macroDefFromSourceLocation( preprocessor(), def );
}

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() || cacheDisabled() )
        return;
    headerCtxStack().back().macroUsed( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() || cacheDisabled() )
        return;
    headerCtxStack().back().macroDefined( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() || cacheDisabled() )
        return;
    headerCtxStack().back().macroUndefined( std::make_pair( name, llvm::StringRef() ) );
}

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
    clang::FileEntry const * entry = headerSearch_->LookupFile( relative, isAngled, 0, dontCare, currentFile, 0, 0, 0, true );
    if ( !entry )
        return;

    fileStack_.push_back( entry );
    if ( !headerSearch_->ShouldEnterIncludeFile( entry, false ) )
    {
        // File will be skipped anyway. Do not search cache.
        fileEntry = entry;
        return;
    }

    Cache::CacheEntry * const cacheHit( cache().findEntry( entry->getName(), preprocessor() ) );
    if ( !cacheHit )
    {
        fileEntry = entry;
        return;
    }
    cacheHit_ = cacheHit;
    cacheEntriesUsed_.insert( cacheHit );
    fileEntry = cacheHit->getFileEntry( preprocessor().getSourceManager() );
}

void HeaderTracker::headerSkipped( llvm::StringRef const relative )
{
    clang::FileEntry const * file( fileStack_.back() );
    fileStack_.pop_back();
    assert( file );
    
    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( file ) );
    assert( cacheHit_ == 0 );
    Header const header( std::make_pair( relative, file->getName() ) );
    if ( !headerCtxStack().empty() )
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
        headerCtxStack().back().addHeader( header );
    }
}

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry )
{
    assert( headerCtxStack().empty() );
    assert( mainFileEntry );
    headerCtxStack().push_back( HeaderCtx( std::make_pair( "<<<MAIN FILE>>>", mainFileEntry->getName() ), 0 ) );
    fileStack_.push_back( mainFileEntry );
}

void HeaderTracker::enterHeader( llvm::StringRef relative )
{
    clang::FileEntry const * file( fileStack_.back() );
    if ( file )
    {
        Header const header( std::make_pair( relative, file->getName() ) );
        if ( !headerCtxStack().empty() )
            headerCtxStack().back().addHeader( header );
        headerCtxStack().push_back( HeaderCtx( header, cacheHit_ ) );
        cacheHit_ = 0;
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
    HeaderCtx & includer( headerCtxStack()[ stackSize - 2 ] );

    includer.addStuff
    (
        headerCtxStack().back().macroUsages(),
        ignoreHeaders ? 0 : &headerCtxStack().back().includedHeaders()
    );

    if ( !headerCtxStack().back().fromCache() )
        headerCtxStack().back().addToCache( cache(), file, sourceManager() );
}


void HeaderTracker::HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file, clang::SourceManager & sourceManager ) const
{
    cache.addEntry( file, usedMacros(), macroUsages(), includedHeaders() );
}

HeaderTracker::Headers HeaderTracker::exitSourceFile()
{
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        Cleanup( HeaderCtxStack & stack ) : stack_( stack ) {}
        ~Cleanup() { stack_.pop_back(); }
    } const cleanup( headerCtxStack() );

    //for ( std::set<Cache::CacheEntry *>::const_iterator iter( cacheEntriesUsed_.begin() ); iter != cacheEntriesUsed_.end(); ++iter )
    //    (*iter)->second.releaseFileEntry( sourceManager() );
    cacheEntriesUsed_.clear();
    return headerCtxStack().back().includedHeaders();
}

llvm::StringRef HeaderTracker::macroDefFromSourceLocation( clang::MacroDirective const * def )
{
    return ::macroDefFromSourceLocation( preprocessor(), def );
}

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;
    headerCtxStack().back().macroUsed( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;
    headerCtxStack().back().macroDefined( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;
    headerCtxStack().back().macroUndefined( std::make_pair( name, llvm::StringRef() ) );
}

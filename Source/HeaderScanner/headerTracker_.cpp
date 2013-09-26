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
    std::pair<clang::FileEntry const *, bool> currentEntry( fileStack_.back() );
    clang::FileEntry const * currentFile = currentEntry.first;
    clang::DirectoryLookup const * dontCare;
    bool system = false;
    clang::FileEntry const * entry = userHeaderSearch_->LookupFile( relative, isAngled, 0, dontCare, currentFile, 0, 0, 0, false );
    if ( !entry )
    {
        system = true;
        entry = systemHeaderSearch_->LookupFile( relative, isAngled, 0, dontCare, currentFile, 0, 0, 0, false );
    }

    if ( !entry )
        return;

    fileStack_.push_back( std::make_pair( entry, system ) );
    if ( cacheDisabled() || !( system ? systemHeaderSearch_ : userHeaderSearch_ )->ShouldEnterIncludeFile( entry, false ) )
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

void HeaderTracker::headerSkipped( llvm::StringRef const relative )
{
    assert( !fileStack_.empty() );
    std::pair<clang::FileEntry const *, bool> currentEntry( fileStack_.back() );
    clang::FileEntry const * file( currentEntry.first );
    assert( file );
    bool const system( currentEntry.second );
    fileStack_.pop_back();

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
            assert( headerInfo.ControllingMacro );
            clang::MacroDirective const * directive( preprocessor().getMacroDirectiveHistory( headerInfo.ControllingMacro ) );
            assert( directive );

            llvm::StringRef const & macroName( headerInfo.ControllingMacro->getName() );
            
            MacroState::const_iterator const iter( macroState().find( macroName ) );
            llvm::StringRef const macroDef( iter == macroState().end() ? llvm::StringRef() : iter->getValue() );
            headerCtxStack().back().macroUsed( macroName, macroDef );
        }
        if ( !system )
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
    headerCtxStack().push_back( HeaderCtx( std::make_pair( "<<<MAIN FILE>>>", mainFileEntry ), CacheEntryPtr(), preprocessor_ ) );
    fileStack_.push_back( std::make_pair( mainFileEntry, false ) );
}

void HeaderTracker::enterHeader( llvm::StringRef relative )
{
    assert( !fileStack_.empty() );
    std::pair<clang::FileEntry const *, bool> currentEntry( fileStack_.back() );
    clang::FileEntry const * file( currentEntry.first );
    assert( file );
    bool const system( currentEntry.second );
    if ( file )
    {
        HeaderName header( std::make_pair( relative, file ) );
        if ( !system )
            headerCtxStack().back().addHeader( header );
        headerCtxStack().push_back( HeaderCtx( header, cacheHit_, preprocessor_ ) );
        cacheHit_.reset();
    }
}

void HeaderTracker::leaveHeader( PreprocessingContext::IgnoredHeaders const & ignoredHeaders )
{
    assert( headerCtxStack().size() > 1 );

    assert( !fileStack_.empty() );
    std::pair<clang::FileEntry const *, bool> currentEntry( fileStack_.back() );
    clang::FileEntry const * file( currentEntry.first );
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
    bool const ignoreHeaders( ignoredHeaders.find( headerCtxStack().back().header().first ) != ignoredHeaders.end() );

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

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    //assert( macroState()[ name ] == macroDefFromSourceLocation( preprocessor_, def ) );
    MacroState::const_iterator const iter( macroState().find( name ) );
    llvm::StringRef const macroDef( iter == macroState().end() ? llvm::StringRef() : iter->getValue() );
    headerCtxStack().back().macroUsed( name, macroDef );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    llvm::StringRef const macroDef( macroDefFromSourceLocation( preprocessor_, def ) );
    llvm::StringMapEntry<llvm::StringRef> * const entry( llvm::StringMapEntry<llvm::StringRef>::Create( name.data(), name.data() + name.size(), macroState().getAllocator(), macroDef ) );
    bool const insertSuccess = macroState().insert( entry );
    // It is OK to #define macro to its current value.
    // If this assertion fires, you most likely messed up the header cache.
    //assert( insertSuccess || macroState()[ name ] == macroDef );
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroDefined( name, macroDef );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    macroState().erase( name );
    if ( headerCtxStack().empty() || cacheDisabled() || headerCtxStack().back().fromCache() )
        return;
    headerCtxStack().back().macroUndefined( name );
}

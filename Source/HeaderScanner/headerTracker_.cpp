#include "headerTracker_.hpp"

#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/HeaderSearch.h"

#include "boost/lambda/bind.hpp"

#include <algorithm>
#include <iostream>
#include <sstream>


namespace
{
    llvm::StringRef macroDefFromSourceLocation( clang::Preprocessor const & preprocessor, clang::MacroDirective const * def )
    {
        clang::SourceManager const & sourceManager( preprocessor.getSourceManager() );
        if ( !def )
            return llvm::StringRef();
        clang::SourceLocation loc( def->getLocation() );
        if ( !loc.isValid() )
            return llvm::StringRef();
        std::pair<clang::FileID, unsigned> spellingLoc( sourceManager.getDecomposedSpellingLoc( loc ) );
        if ( spellingLoc.first.isInvalid() )
            throw std::runtime_error( "Invalid FileID." );
        clang::FileEntry const * fileEntry( sourceManager.getFileEntryForID( spellingLoc.first ) );
        bool invalid;
        llvm::MemoryBuffer const * buffer( sourceManager.getBuffer( spellingLoc.first, loc, &invalid ) );
        assert( !invalid );
        // Find beginning of directive.
        char const * defLoc( buffer->getBufferStart() + spellingLoc.second );
        // Find end of directive.
        clang::Lexer rawLex( loc, preprocessor.getLangOpts(),
            defLoc, defLoc, buffer->getBufferEnd() );
        rawLex.setParsingPreprocessorDirective( true );
        clang::Token rawToken;
        do { rawLex.LexFromRawLexer( rawToken ); } while ( rawToken.isNot( clang::tok::eod ) );
        std::pair<clang::FileID, unsigned> endSpellingLoc( sourceManager.getDecomposedSpellingLoc( rawToken.getLocation() ) );
        assert( spellingLoc.first == endSpellingLoc.first );
        assert( spellingLoc.second < endSpellingLoc.second );
        std::size_t size( endSpellingLoc.second - spellingLoc.second );
        while ( defLoc[ size - 1 ] == ' ' || defLoc[ size - 1 ] == '\t' )
            size--;
        return llvm::StringRef( defLoc, size );
    }

    bool isMacroCurrent( Macro const & macro, clang::Preprocessor const & preprocessor )
    {
        llvm::StringRef const macroName( macro.first );
        llvm::StringRef const macroDef( macro.second );

        clang::IdentifierInfo * const identifier( preprocessor.getIdentifierInfo( macroName ) );
        assert( identifier );
        clang::MacroDirective const * const currentMacroDir( preprocessor.getMacroDirective( identifier ) );

        return macroDef == macroDefFromSourceLocation( preprocessor, currentMacroDir );
    }
}

clang::FileEntry const * Cache::CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    assert( !overridden_ );
    if ( !fileEntry_ )
    {
        static unsigned counter( 0 );
        std::stringstream filename;
        filename << "_file" << counter++;
        fileEntry_ = sourceManager.getFileManager().getVirtualFile( filename.str(), filename.str().size(), 0 );
    }

    // Cache the result.
    std::string buffer;
    llvm::raw_string_ostream defineStream( buffer );
    for ( MacroMap::const_iterator iter( definedMacros.begin() ); iter != definedMacros.end(); ++iter )
    {
        assert( iter->second.data() );
        defineStream << "#define " << iter->second << '\n';
    }
    for ( MacroMap::const_iterator iter( undefinedMacros.begin() ); iter != undefinedMacros.end(); ++iter )
    {
        assert( !iter->second.data() );
        defineStream << "#undef" << iter->first << '\n';
    }
    defineStream << '\0';

    std::string const & content( defineStream.str() );
    static unsigned counter( 0 );
    std::stringstream filename;
    filename << "_file" << counter++;
    llvm::MemoryBuffer * const memoryBuffer(
        llvm::MemoryBuffer::getMemBufferCopy( content, "" ) );
    sourceManager.overrideFileContents( fileEntry_, memoryBuffer, true );
    overridden_ = true;
    return fileEntry_;
}

void Cache::CacheEntry::releaseFileEntry( clang::SourceManager & sourceManager )
{
    assert( fileEntry_ );
    assert( overridden_ );
    sourceManager.disableFileContentsOverride( fileEntry_ );
}

Cache::CacheHit * Cache::findEntry( clang::FileEntry const * file, clang::Preprocessor const & preprocessor )
{
    HeadersInfo::iterator const iter( headersInfo().find( file ) );
    if ( iter == headersInfo().end() )
        return 0;

    for
    (
        HeaderInfo::iterator headerInfoIter( iter->second.begin() );
        headerInfoIter != iter->second.end();
        ++headerInfoIter
    )
    {
        MacroSet const & inputMacros( headerInfoIter->first );
        bool isMatch( true );

        struct MacroIsNotCurrent
        {
            clang::Preprocessor const & pp_;
            
            explicit MacroIsNotCurrent( clang::Preprocessor const & pp ) : pp_( pp ) {}

            bool operator()( Macro const & macro )
            {
                return !isMacroCurrent( macro, pp_ );
            }
        } macroIsNotCurrent( preprocessor );
        
        if
        (
            std::find_if
            (
                inputMacros.begin(), inputMacros.end(),
                macroIsNotCurrent
            ) != inputMacros.end()
        )
            continue;

        return &*headerInfoIter;
    }
    return 0;
}


void HeaderTracker::findFile( llvm::StringRef relative, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    // If cacheHit_ then we are in a fake header which does not include
    // anything.
    assert( cacheHit_ == 0 );

    // Find the actual file being used.
    assert( !fileStack_.empty() );
    clang::FileEntry const * currentFile( fileStack_.back() );
    clang::DirectoryLookup const * dontCare;
    clang::FileEntry const * entry = headerSearch_->LookupFile( relative, isAngled, 0, dontCare, currentFile, 0, 0, 0, true );
    if ( !entry )
        return;

    if ( !headerSearch_->ShouldEnterIncludeFile( entry, false ) )
    {
        // File will be skipped anyway. Do not search cache.
        fileEntry = entry;
        return;
    }

    fileStack_.push_back( entry );
    std::string const & filename( entry->getName() );

    Cache::CacheHit * const cacheHit( cache().findEntry( entry, preprocessor() ) );
    if ( !cacheHit )
    {
        fileEntry = entry;
        return;
    }

    cacheHit_ = cacheHit;
    fileEntry = cacheHit->second.getFileEntry( preprocessor().getSourceManager() );
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
    headerCtxStack().push_back( HeaderCtx( std::make_pair( "<<<MAIN FILE>>>", mainFileEntry->getName() ) ) );
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
        headerCtxStack().push_back( HeaderCtx( header ) );
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
        Cache::CacheHit * & cacheHit_;

        Cleanup( HeaderCtxStack & stack, Cache::CacheHit * & cacheHit )
            :
            stack_( stack ),
            cacheHit_( cacheHit )
        {}

        ~Cleanup()
        {
            stack_.pop_back();
            cacheHit_ = 0;
        }
    } const cleanup( headerCtxStack(), cacheHit_ );

    HeaderCtxStack::size_type const stackSize( headerCtxStack().size() );
    // Propagate the results to the file which included us.
    bool const ignoreHeaders( ignoredHeaders.find( headerCtxStack().back().header().first ) != ignoredHeaders.end() );
    HeaderCtx & includer( headerCtxStack()[ stackSize - 2 ] );

    if ( cacheHit_ )
    {
        includer.addStuff
        (
            cacheHit_->first,
            cacheHit_->second.definedMacros,
            cacheHit_->second.undefinedMacros,
            ignoreHeaders ? 0 : &cacheHit_->second.headers
        );
    }
    else
    {
        includer.addStuff
        (
            headerCtxStack().back().usedMacros(),
            headerCtxStack().back().definedMacros(),
            headerCtxStack().back().undefinedMacros(),
            ignoreHeaders ? 0 : &headerCtxStack().back().includedHeaders()
        );

        headerCtxStack().back().addToCache( cache(), file, sourceManager() );
    }
}

void HeaderTracker::HeaderCtx::addToCache( Cache & cache, clang::FileEntry const * file, clang::SourceManager & sourceManager ) const
{
    cache.addEntry( file, usedMacros(), definedMacros(), undefinedMacros(), includedHeaders() );
}

HeaderTracker::Headers HeaderTracker::exitSourceFile()
{
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        Cleanup( HeaderCtxStack & stack ) : stack_( stack ) {}
        ~Cleanup() { stack_.pop_back(); }
    } const cleanup( headerCtxStack() );
    return headerCtxStack().back().includedHeaders();
}

llvm::StringRef HeaderTracker::macroDefFromSourceLocation( clang::MacroDirective const * def )
{
    return ::macroDefFromSourceLocation( preprocessor(), def );
}

void HeaderTracker::macroUsed( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().macroUsed( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().macroDefined( std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().macroUndefined( std::make_pair( name, llvm::StringRef() ) );
}

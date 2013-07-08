#include "headerTracker_.hpp"

#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/HeaderSearch.h"

#include "boost/lambda/bind.hpp"

#include <algorithm>
#include <iostream>
#include <sstream>


void HeaderTracker::findFile( llvm::StringRef relative, bool const isAngled, clang::FileEntry const * & fileEntry )
{
    // If cacheHit_ then we should be processing empty, fake, injected header.
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
    }

    fileStack_.push_back( entry );
    std::string const & filename( entry->getName() );

    HeaderCacheSt::iterator const iter( cache().find( entry ) );
    if ( iter == cache().end() )
    {
        fileEntry = entry;
        return;
    }
    for ( HeaderShortCircuit::iterator shortCircuit( iter->second.begin() ); shortCircuit != iter->second.end(); ++shortCircuit )
    {
        MacroSet const & inputMacros( shortCircuit->first );
        bool isMatch( true );
        for ( MacroSet::const_iterator macroIter( inputMacros.begin() ); macroIter != inputMacros.end(); ++macroIter )
        {
            std::string const & macroName( macroIter->first );
            MacroDef const & macroDef( macroIter->second );

            clang::IdentifierInfo * const identifier( preprocessor().getIdentifierInfo( macroName ) );
            assert( identifier );
            clang::MacroDirective const * const currentMacroDir( preprocessor().getMacroDirective( identifier ) );

            MacroDef currentMacroDef = macroDefFromSourceLocation( currentMacroDir );
            if ( currentMacroDef != macroDef )
            {
                isMatch = false;
                break;
            }
        }

        if ( isMatch )
        {
            // We have a match. Store short circuit.
            // We will use it if we actually enter this header.
            cacheHit_ = &*shortCircuit;
            fileEntry = shortCircuit->second.fileEntry;
            return;
        }
    }
    fileEntry = entry;
}

void HeaderTracker::headerSkipped( std::string const & relative )
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

            headerCtxStack().back().addMacro
            (
                MacroUsage::macroUsed,
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

void HeaderTracker::enterHeader( std::string const & relative )
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

void HeaderTracker::HeaderCtx::addMacro( MacroUsage::Enum usage, Macro const & macro )
{
    macroUsages_.push_back( std::make_pair( usage, macro ) );
}

void HeaderTracker::HeaderCtx::addHeader( Header const & header )
{
    includedHeaders_.insert( header );
}

void HeaderTracker::HeaderCtx::normalize()
{
    // Search for all undefines.
    typedef std::set<std::size_t> Positions;
    typedef std::map<std::string, Positions> MacroPositions;
    MacroPositions definedMacros;
    MacroPositions undefinedMacros;
    MacroPositions usedMacros;
    std::size_t pos( 0 );
    for ( MacroUsages::const_iterator iter( macroUsages_.begin() ); iter != macroUsages_.end(); ++iter, ++pos )
    {
        if ( iter->first == MacroUsage::macroDefined   )
            definedMacros  [ iter->second.first ].insert( pos );
        if ( iter->first == MacroUsage::macroUndefined )
            undefinedMacros[ iter->second.first ].insert( pos );
        usedMacros[ iter->second.first ].insert( pos );
    }

    Positions positionsToRemove;
    for ( MacroPositions::iterator undefIter( undefinedMacros.begin() ); undefIter != undefinedMacros.end(); ++undefIter )
    {
        MacroPositions::iterator const defIter( definedMacros.find( undefIter->first ) );
        if ( defIter == definedMacros.end() )
            continue;

        // We can remove everything, from the first define to the last undefine,
        // including any usages in between.
        std::size_t const start( *defIter->second.begin() );
        std::size_t const stop( *undefIter->second.rbegin() );
        Positions const & positions( usedMacros[ defIter->first ] );
        for ( Positions::const_iterator posIter( positions.begin() ); posIter != positions.end(); ++posIter )
            if ( *posIter >= start && *posIter <= stop )
                positionsToRemove.insert( *posIter );
    }

    for ( Positions::const_reverse_iterator posIter( positionsToRemove.rbegin() ); posIter != positionsToRemove.rend(); ++posIter )
    {
        MacroUsages::iterator iter( macroUsages_.begin() );
        std::advance( iter, *posIter );
        macroUsages_.erase( iter );
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
        HeaderShortCircuit::value_type * & cacheHit_;
        Cleanup( HeaderCtxStack & stack,
            HeaderShortCircuit::value_type * & shortCircuit )
            : stack_( stack ), cacheHit_( shortCircuit )
        {}
        ~Cleanup()
        {
            stack_.pop_back();
            cacheHit_ = 0;
        }
    } const cleanup( headerCtxStack(), cacheHit_ );

    Headers const * headers( 0 );
    MacroUsages const * macroUsages( 0 );
    if ( cacheHit_ )
    {
        headers = &cacheHit_->second.headers;
        macroUsages = &cacheHit_->second.macroUsages;
    }
    else
    {
        headers = &headerCtxStack().back().includedHeaders();
        macroUsages = &headerCtxStack().back().macroUsages();

        // Cache the result.
        std::string buffer;
        llvm::raw_string_ostream defineStream( buffer );
        for ( MacroUsages::const_iterator iter( macroUsages->begin() ); iter != macroUsages->end(); ++iter )
        {
            MacroUsage::Enum const macroUsage( iter->first );
            std::string const & macroName( iter->second.first );
            MacroDef const & macroDef( iter->second.second );
            if ( macroUsage == MacroUsage::macroUndefined )
            {
                assert( !macroDef );
                defineStream << "#undef " << macroName << '\n';
            }
            if ( macroUsage == MacroUsage::macroDefined )
            {
                assert( macroDef );
                defineStream << "#define " << *macroDef << '\n';
            }
        }
        defineStream << '\0';

        std::string const & content( defineStream.str() );
        static unsigned counter( 0 );
        std::stringstream filename;
        filename << "_file" << counter++;
        clang::FileEntry const * fileEntry( sourceManager_.getFileManager().getVirtualFile( filename.str(), filename.str().size(), 0 ) );
        llvm::MemoryBuffer * const memoryBuffer(
            llvm::MemoryBuffer::getMemBufferCopy( content, "" ) );
        sourceManager_.overrideFileContents( fileEntry, memoryBuffer, true );

        cache()[ file ].insert
        (
            std::make_pair
            (
                headerCtxStack().back().usedMacros(),
                ShortCircuitEntry
                (
                    fileEntry,
                    *macroUsages,
                    *headers
                )
            )
        );
    }

    HeaderCtxStack::size_type const stackSize( headerCtxStack().size() );
    // Propagate the results to the file which included us.
    bool const ignoreHeaders( ignoredHeaders.find( headerCtxStack().back().header().first ) != ignoredHeaders.end() );
    headerCtxStack()[ stackSize - 2 ].addStuff( macroUsages, ignoreHeaders ? 0 : headers );
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



HeaderTracker::MacroDef HeaderTracker::macroDefFromSourceLocation( clang::MacroDirective const * def )
{
    if ( !def )
        return boost::none;
    clang::SourceLocation loc( def->getLocation() );
    if ( !loc.isValid() )
        return boost::none;
    std::pair<clang::FileID, unsigned> spellingLoc( sourceManager().getDecomposedSpellingLoc( loc ) );
    if ( spellingLoc.first.isInvalid() )
        throw std::runtime_error( "Invalid FileID." );
    clang::FileEntry const * fileEntry( sourceManager().getFileEntryForID( spellingLoc.first ) );
    bool invalid;
    llvm::MemoryBuffer const * buffer( sourceManager().getBuffer( spellingLoc.first, loc, &invalid ) );
    assert( !invalid );
    // Find beginning of directive.
    char const * defLoc( buffer->getBufferStart() + spellingLoc.second );
    // Find end of directive.
    clang::Lexer rawLex( loc, preprocessor().getLangOpts(),
        defLoc, defLoc, buffer->getBufferEnd() );
    rawLex.setParsingPreprocessorDirective( true );
    clang::Token rawToken;
    do { rawLex.LexFromRawLexer( rawToken ); } while ( rawToken.isNot( clang::tok::eod ) );
    std::pair<clang::FileID, unsigned> endSpellingLoc( sourceManager().getDecomposedSpellingLoc( rawToken.getLocation() ) );
    assert( spellingLoc.first == endSpellingLoc.first );
    assert( spellingLoc.second < endSpellingLoc.second );
    std::size_t size( endSpellingLoc.second - spellingLoc.second );
    while ( defLoc[ size - 1 ] == ' ' || defLoc[ size - 1 ] == '\t' )
        size--;
    return std::string( defLoc, size );
}

void HeaderTracker::macroUsed( std::string const & name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().addMacro( MacroUsage::macroUsed, std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroDefined( std::string const & name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().addMacro( MacroUsage::macroDefined, std::make_pair( name, macroDefFromSourceLocation( def ) ) );
}

void HeaderTracker::macroUndefined( std::string const & name, clang::MacroDirective const * def )
{
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().addMacro( MacroUsage::macroUndefined, std::make_pair( name, boost::none ) );
}

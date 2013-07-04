#include "headerTracker_.hpp"

#include "clang/Lex/Preprocessor.h"

#include "boost/lambda/bind.hpp"

#include <algorithm>
#include <iostream>

bool HeaderTracker::inclusionDirective( std::string const & relative, clang::FileEntry const * fileEntry, std::string * & str )
{
    //std::cout << "Trying to override '" << relative << "'.\n";
    if ( mustNotOverride_.find( fileEntry ) != mustNotOverride_.end() )
    {
        //std::cout << "Did not override due to 'mustNotOverride'\n";
        return false;
    }

    std::string const & filename( fileEntry->getName() );

    // If shortCircuit_ then we should be processing empty, fake, injected header.
    assert( shortCircuit_ == 0 );

    HeaderCacheSt::iterator const iter( cache().find( std::make_pair( relative, filename ) ) );
    if ( iter == cache().end() )
    {
        //std::cout << "No cache for '" << relative << "'.\n";
        return false;
    }
    for ( HeaderShortCircuit::iterator shortCircuit( iter->second.begin() ); shortCircuit != iter->second.end(); ++shortCircuit )
    {
        assert( shortCircuit->second.session <= session_ );
        // If the cache was made in this session do not use it.
        // It will invalidate macro definitions for macros already in use.
        if ( shortCircuit->second.session == session_ )
            continue;

        MacroSet const & inputMacros( shortCircuit->first );
        bool isMatch( true );
        for ( MacroSet::const_iterator macroIter( inputMacros.begin() ); macroIter != inputMacros.end(); ++macroIter )
        {
            std::string const & macroName( macroIter->first );
            MacroDef const & macroDef( macroIter->second );

            clang::IdentifierInfo * const identifier( preprocessor().getIdentifierInfo( macroName ) );
            assert( identifier );
            clang::MacroDirective const * const currentMacroDir( preprocessor().getMacroDirective( identifier ) );

            MacroDef currentMacroDef;
            if ( currentMacroDir && currentMacroDir->isFromPCH() )
            {
                MacroDefMap::iterator const iter( currentFakeMacros_.find( macroName ) );
                assert( iter != currentFakeMacros_.end() );
                currentMacroDef = iter->second;
            }
            else
                currentMacroDef = macroDefFromSourceLocation( currentMacroDir );

            // If the location is same - macros are same
            if ( currentMacroDef != macroDef )
            {
                //std::cout << "Cache mismatch due to " << macroName << ".\n";
                //std::cout << "Type " << currentMacroDef.type << '-' << macroDef.type << '\n';
                //std::cout << "Def " << currentMacroDef.defStr << '-' << macroDef.defStr << '\n';
                isMatch = false;
                break;
            }
        }
        if ( isMatch )
        {
            // We have a match. Store short circuit.
            // We will use it if we actually enter this header.
            shortCircuit_ = &*shortCircuit;

            OverriddenHeaderContents::key_type const key( std::make_pair( relative, shortCircuit_->first ) );
            OverriddenHeaderContents::iterator const iter( fakeMacroBuffers_.find( key ) );
            if ( iter != fakeMacroBuffers_.end() )
            {
                str = &iter->second;
                return true;
            }

            llvm::raw_string_ostream defineStream( fakeMacroBuffers_[ key ] );

            ShortCircuitEntry const & entry( shortCircuit_->second );
            MacroUsages const & usedMacros( entry.macroUsages );
            for ( MacroUsages::const_iterator iter( usedMacros.begin() ); iter != usedMacros.end(); ++iter )
            {
                MacroUsage::Enum const macroUsage( iter->first );
                std::string const & macroName( iter->second.first );
                MacroDef const & macroDef( iter->second.second );
                currentFakeMacros_[ macroName ] = macroDef;
                if ( macroUsage == MacroUsage::macroUndefined )
                {
                    defineStream << "#undef " << macroName << '\n';
                }
                if ( macroUsage == MacroUsage::macroDefined )
                {
                    defineStream << "#define " << macroDef << '\n';
                }
            }
            str = &defineStream.str();
            return true;
        }
    }
    //std::cout << "Nothing found in cache.\n";
    return false;
}

void HeaderTracker::headerSkipped( std::string const & relative, std::string const & filename )
{
    assert( shortCircuit_ == 0 );
    Header const header( std::make_pair( relative, filename ) );
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().addHeader( header );
}

void HeaderTracker::enterHeader( std::string const & relative, std::string const & filename )
{
    Header const header( std::make_pair( relative, filename ) );
    if ( !headerCtxStack().empty() )
        headerCtxStack().back().addHeader( header );
    headerCtxStack().push_back( HeaderCtx( header ) );
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
        std::size_t jorgula( *posIter );
        std::advance( iter, *posIter );
        macroUsages_.erase( iter );
    }
}



HeaderTracker::Headers HeaderTracker::leaveHeader( PreprocessingContext::IgnoredHeaders const & ignoredHeaders )
{
    struct Cleanup
    {
        HeaderCtxStack & stack_;
        HeaderShortCircuit::value_type * & shortCircuit_;
        Cleanup( HeaderCtxStack & stack,
            HeaderShortCircuit::value_type * & shortCircuit )
            : stack_( stack ), shortCircuit_( shortCircuit )
        {}
        ~Cleanup()
        {
            stack_.pop_back();
            shortCircuit_ = 0;
        }
    } const cleanup( headerCtxStack(), shortCircuit_ );

    Headers const * headers( 0 );
    MacroUsages const * macroUsages( 0 );
    if ( shortCircuit_ )
    {
        headers = &shortCircuit_->second.headers;
        macroUsages = &shortCircuit_->second.macroUsages;
    }
    else
    {
        headers = &headerCtxStack().back().includedHeaders();
        macroUsages = &headerCtxStack().back().macroUsages();

        // Cache the result.
        headerCtxStack().back().normalize();
        cache()[ headerCtxStack().back().header() ].insert
        (
            std::make_pair
            (
                headerCtxStack().back().usedMacros(),
                ShortCircuitEntry
                (
                    session_,
                    headerCtxStack().back().macroUsages(),
                    headerCtxStack().back().includedHeaders()
                )
            )
        );
    }

    HeaderCtxStack::size_type const stackSize( headerCtxStack().size() );
    if ( stackSize > 1 )
    {
        // If there is a header which included this one, propagate the results.
        bool const ignoreHeaders( ignoredHeaders.find( headerCtxStack().back().header().first ) != ignoredHeaders.end() );
        headerCtxStack()[ stackSize - 2 ].addStuff( macroUsages, ignoreHeaders ? 0 : headers );
        return Headers();
    }
    else
    {
        // This means we are leaving the main source file.
        currentFakeMacros_.clear();
        fakeMacroBuffers_.clear();
        mustNotOverride_.clear();
        session_++;
        assert( !shortCircuit_ );
        return *headers;
    }
}

HeaderTracker::MacroDef HeaderTracker::macroDefFromSourceLocation( clang::MacroDirective const * def )
{
    if ( !def )
        return MacroDef();
    assert( !def->isFromPCH() );
    clang::SourceLocation loc( def->getLocation() );
    if ( !loc.isValid() )
        return MacroDef();
    std::pair<clang::FileID, unsigned> spellingLoc( sourceManager().getDecomposedSpellingLoc( loc ) );
    if ( spellingLoc.first.isInvalid() )
    {
        //std::cout << "Invalid FileID :(\n";
        throw std::runtime_error( "Invalid FileID." );
    }
    clang::FileEntry const * fileEntry( sourceManager().getFileEntryForID( spellingLoc.first ) );
    assert( !sourceManager().isFileOverridden( fileEntry ) );
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
    return MacroDef( defLoc, endSpellingLoc.second - spellingLoc.second );
}

void HeaderTracker::macroUsed( std::string const & name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;

    Macro macro;
    if ( def && def->isFromPCH() )
    {
        // Someone is using our fake macro. Find its real definition.
        MacroDefMap::const_iterator const iter( currentFakeMacros_.find( name ) );
        assert( iter != currentFakeMacros_.end() );
        headerCtxStack().back().addMacro( MacroUsage::macroUsed, std::make_pair( name, iter->second ) );
    }
    else
    {
        headerCtxStack().back().addMacro( MacroUsage::macroUsed, std::make_pair( name, macroDefFromSourceLocation( def ) ) );
    }

}

void HeaderTracker::macroDefined( std::string const & name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;

    MacroDef macroDef;
    if ( inOverriddenFile() )
    {
        const_cast<clang::MacroDirective *>( def )->setIsFromPCH();
        MacroDefMap::const_iterator const iter( currentFakeMacros_.find( name ) );
        assert( iter != currentFakeMacros_.end() );
        macroDef = iter->second;
    }
    else
    {
        assert( def );
        macroDef = macroDefFromSourceLocation( def );
        clang::FileID const fileId( sourceManager().getFileID( def->getLocation() ) );
        assert( !fileId.isInvalid() );
        clang::FileEntry const * fileEntry( sourceManager().getFileEntryForID( fileId ) );
        // Once a macro definition is used, the defining file is no longer
        // viable for override.
        if ( !def->isFromPCH() && fileEntry )
            mustNotOverride_.insert( fileEntry );
    }

    headerCtxStack().back().addMacro( MacroUsage::macroDefined, std::make_pair( name, macroDef ) );
}

void HeaderTracker::macroUndefined( std::string const & name, clang::MacroDirective const * def )
{
    if ( headerCtxStack().empty() )
        return;

    headerCtxStack().back().addMacro( MacroUsage::macroUndefined, std::make_pair( name, MacroDef() ) );
}

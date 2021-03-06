#include "headerTracker_.hpp"

#include "contentCache_.hpp"
#include "macroState_.hpp"
#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/HeaderSearch.h>
#include <llvm/Support/Path.h>

#include <boost/spirit/include/karma.hpp>
#include <boost/thread/lock_algorithms.hpp>
#include <boost/thread/shared_mutex.hpp>

#include <algorithm>
#include <memory>
#include <fstream>
#include <iostream>
#include <sstream>
#include <windows.h>

#ifdef DEBUG_HEADERS
std::ofstream logging_stream( "header_log.txt" );
#endif

namespace
{
    template <typename T>
    struct PopBackGuard
    {
        PopBackGuard( T & t ) : t_( t ) {}
        ~PopBackGuard() { t_.pop_back(); }

        T & t_;
    };
}

Header IncludedHeaders::makeHeader() const
{
    Header result =
    {
        dir,
        name,
        ContentCache::singleton().getOrCreate( file->getName() ).get(),
        relative
    };
    return result;
}

MacroName macroForPragmaOnce( clang::FileEntry const & entry )
{
    llvm::sys::fs::UniqueID const & fileId = entry.getUniqueID();
    std::string result;
    using namespace boost::spirit::karma;
    generate( std::back_inserter( result ),
        lit( "____pragma_once__" ) << ulong_long << lit("_") << ulong_long,
        fileId.getDevice(), fileId.getFile() );
    return MacroName( result );
}

void HeaderTracker::inclusionDirective( llvm::StringRef searchPath, llvm::StringRef relativePath, llvm::StringRef fileName, bool isAngled, clang::FileEntry const * entry )
{
    commitMacros();
    assert( !fileStack_.empty() );
    bool const relativeToParent( !isAngled && ( fileStack_.back().file->getDir()->getName() == searchPath ) );

    Dir dir;
    HeaderName headerName;

    if ( relativeToParent )
    {
        dir =  Dir( fileStack_.back().dir );
        llvm::StringRef const parentFilename = fileStack_.back().name.get();
        std::size_t const slashPos = parentFilename.find_last_of('/');
        if ( slashPos == llvm::StringRef::npos )
            headerName = HeaderName( relativePath );
        else
        {
            llvm::SmallString<512> fileName( parentFilename.data(), parentFilename.data() + slashPos + 1 );
            fileName.append( relativePath );
            headerName = HeaderName( fileName.str() );
        }
    }
    else
    {
        dir = Dir( searchPath );
        headerName = HeaderName( relativePath );
    }

    fileStack_.emplace_back
    (
        dir,
        headerName,
        relativeToParent,
        entry
    );
}

void HeaderTracker::enterFile()
{
    fileStack_.back().pHeaderCtx.reset
    (
        new HeaderCtx
        (
            macroState_,
            fileStack_.back().file,
            replacement_,
            cacheHit_,
            pCurrentCtx_,
            preprocessor_
        )
    );
    pCurrentCtx_ = fileStack_.back().pHeaderCtx.get();
    if ( !cacheHit_ )
        currentHeaderCtx().macroUsed( macroForPragmaOnce( *fileStack_.back().file ) );
    replacement_ = 0;
    cacheHit_.reset();
}

void HeaderTracker::exitFile()
{
    HeaderCtx * result = pCurrentCtx_;
    pCurrentCtx_ = pCurrentCtx_->parent();
    fileStack_.back().pHeaderCtx.reset();
    if ( hasCurrentHeaderCtx() )
        currentHeaderCtx().addHeader( fileStack_.back().makeHeader() );
}

void HeaderTracker::replaceFile( clang::FileEntry const * & entry )
{
    // Here we handle the case where header with #pragma once is included
    // implicitly, via a cache entry. In this case Clang will not skip
    // this header in usual manner, so we must cheat it to include an
    // empty file.
    // TODO: Try avoiding calling (expensive) macroForPragmaOnce() on every
    // (non-skipped) include directive.
    if ( currentHeaderCtx().getMacroValue( macroForPragmaOnce( *entry ) ) != undefinedMacroValue )
    {
        clang::FileEntry const * result( sourceManager().getFileManager().getVirtualFile( "__empty_file", 0, 0 ) );
        if ( !sourceManager().isFileOverridden( result ) )
            sourceManager().overrideFileContents( result, llvm::MemoryBuffer::getMemBuffer( "" ) );
        entry = result;
        replacement_ = result;
        return;
    }

    if
    (
        !cacheDisabled() &&
        ( cacheHit_ = cache().findEntry( entry->getUniqueID(), searchPathId_,
            macroState_ ) )
    )
    {
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Found cache hit.\n";
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "UsedMacros:\n";
    cacheHit_->forEachUsedMacro( [&]( Macro const & macro )
    {
        for ( unsigned int x = 0; x < fileStack_.size(); ++x )
            logging_stream << "    ";
        logging_stream << macro.first.get().str().str() << ' ' << macro.second.get().str().str() << '\n';
    });
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "ChangedMacros:\n";
    cacheHit_->macroState().forEachMacro( [&]( Macro const & macro )
    {
        for ( unsigned int x = 0; x < fileStack_.size(); ++x )
            logging_stream << "    ";
        logging_stream << macro.first.get().str().str() << ' ' << macro.second.get().str().str() << '\n';
    });
#endif
        // There is a hit in cache!
        entry = cacheHit_->getFileEntry( sourceManager() );
        replacement_ = entry;
        std::pair<UsedCacheEntries::const_iterator, bool> const insertResult =
            usedCacheEntries_.insert( std::make_pair( entry, cacheHit_ ) );
        assert( insertResult.first->second == cacheHit_ );
    }
}

void HeaderTracker::headerSkipped()
{
    assert( !fileStack_.empty() );
    assert( hasCurrentHeaderCtx() );
    IncludedHeaders const & hwf( fileStack_.back() );
    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Header skipped: '" << std::string( fileStack_.back().file->getName() ) << "'\n";
#endif

    assert( preprocessor().getHeaderSearchInfo().isFileMultipleIncludeGuarded( hwf.file ) );
    assert( !cacheHit_ );

    if ( !cacheDisabled() )
    {
        clang::HeaderSearch const & headerSearch( preprocessor().getHeaderSearchInfo() );
        clang::HeaderFileInfo headerFileInfo;
        bool const mustSucceed = headerSearch.tryGetFileInfo( hwf.file, headerFileInfo );
        assert( mustSucceed );
        assert( !headerFileInfo.ControllingMacroID );
        currentHeaderCtx().macroUsed( macroForPragmaOnce( *hwf.file ) );
        if ( !headerFileInfo.isPragmaOnce )
        {
            assert( headerFileInfo.ControllingMacro );
            currentHeaderCtx().macroUsed( MacroName( headerFileInfo.ControllingMacro->getName() ) );
        }
    }
    
    currentHeaderCtx().addHeader( hwf.makeHeader() );
}

clang::SourceManager & HeaderTracker::sourceManager() const
{
    return preprocessor_.getSourceManager();
}

void HeaderTracker::enterSourceFile( clang::FileEntry const * mainFileEntry, llvm::StringRef fileName )
{
    assert( !hasCurrentHeaderCtx() );
    assert( mainFileEntry );
    fileStack_.emplace_back
    (
        Dir( mainFileEntry->getDir()->getName() ),
        HeaderName( llvm::sys::path::filename( fileName ) ),
        true,
        mainFileEntry
    );
#ifdef DEBUG_HEADERS
    logging_stream << "Entering source file: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif

    enterFile();
}

void HeaderTracker::enterHeader()
{
    assert( !fileStack_.empty() );
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Entering header: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    enterFile();
}

void HeaderTracker::leaveHeader()
{
    assert( currentHeaderCtx().parent() );

    assert( !fileStack_.empty() );

#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Leaving header: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    PopBackGuard<IncludeStack> const popIncludeStack( fileStack_ );

    if ( !cacheDisabled() && currentHeaderCtx().isViableForCache() )
        currentHeaderCtx().addToCache( cache(), searchPathId_, fileStack_.back().file );
    currentHeaderCtx().propagateToParent();
    exitFile();
}

void HeaderCtx::addToCache( Cache & cache, std::size_t const searchPathId, clang::FileEntry const * file )
{
    assert( !cacheHit_ );

    MacroState changedMacros;
    for ( MacroName const & macroName : changedHere_ )
        changedMacros.defineMacro( macroName, getMacroValue( macroName ) );

    cacheHit_ = cache.addEntry(
        file->getUniqueID(),
        searchPathId,
        usedHere_,
        std::move( changedMacros ),
        std::move( includedHeaders_ )
    );
}

HeaderTracker::HeaderTracker( clang::Preprocessor & preprocessor, std::size_t searchPathId, Cache * cache )
    :
    preprocessor_( preprocessor ),
    searchPathId_( searchPathId ),
    pCurrentCtx_( 0 ),
    replacement_( 0 ),
    cache_( cache ),
    conditionStack_( preprocessor, [this]( llvm::StringRef str )
    {
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro used: '" << str.str() << '\'' << std::endl;
#endif
        currentHeaderCtx().macroUsed( MacroName( str ) );
    })
{
}

void HeaderTracker::exitSourceFile( Headers & headers )
{
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Leaving source file: '" << std::string( fileStack_.back().file->getName() ) << '\'' << std::endl;
#endif
    headers = std::move( currentHeaderCtx().includedHeaders() );
    // Undo cache overrides in source manager.
    for ( UsedCacheEntries::value_type const & entry : usedCacheEntries_ )
    {
        assert( sourceManager().isFileOverridden( entry.first ) );
        sourceManager().disableFileContentsOverride( entry.first );
    }
    // Remove ref from cache entries.
    usedCacheEntries_.clear();
    exitFile();
}

void HeaderTracker::macroUsed( llvm::StringRef name )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro possibly used: '" << name.str() << '\'' << std::endl;
#endif
    conditionStack_.addMacro( name );
}

namespace
{
    MacroValue macroValueFromDirective( clang::Preprocessor const & preprocessor, llvm::StringRef const macroName, clang::MacroDirective const * def )
    {
        assert( def );
        clang::MacroInfo const * macroInfo( def->getMacroInfo() );
        assert( macroInfo );
        assert( !macroInfo->isBuiltinMacro() );
        clang::SourceLocation const startLoc( macroInfo->getDefinitionLoc() );
        assert( !startLoc.isInvalid() );
        clang::SourceManager & sourceManager( preprocessor.getSourceManager() );
        std::pair<clang::FileID, unsigned> startSpellingLoc( sourceManager.getDecomposedExpansionLoc( startLoc ) );
        // We already know macro name, skip that.
        startSpellingLoc.second += macroName.size();
        bool invalid;
        llvm::StringRef const buffer( sourceManager.getBufferData( startSpellingLoc.first, &invalid ) );
        assert( !invalid );
        char const * const macroStart = buffer.data() + startSpellingLoc.second;
        unsigned int const tokCount( macroInfo->getNumTokens() );
        llvm::StringRef result;
        if ( !tokCount )
        {
            char const * end = macroStart;
            if ( !macroInfo->isFunctionLike() )
                return MacroValue( "" );

            while ( *end != ')' ) ++end;
            return MacroValue( llvm::StringRef( macroStart, end - macroStart ) );
        }
        else
        {
            clang::Token const & lastToken( macroInfo->getReplacementToken( tokCount - 1 ) );
            clang::SourceLocation const endLoc( lastToken.getLocation() );
            std::pair<clang::FileID, unsigned> endSpellingLoc( sourceManager.getDecomposedExpansionLoc( endLoc ) );
            endSpellingLoc.second += lastToken.getLength();
            assert( startSpellingLoc.first == endSpellingLoc.first );
            assert( startSpellingLoc.second <= endSpellingLoc.second );
            return MacroValue( llvm::StringRef( macroStart, endSpellingLoc.second - startSpellingLoc.second ) );
        }
    }
}  // anonymous namespace

void HeaderTracker::macroDefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( def->getMacroInfo()->isBuiltinMacro() )
        return;
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    commitMacros();
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro defined: '" << name.str() << '\'' << std::endl;
#endif
    currentHeaderCtx().macroDefined( MacroName( name ), macroValueFromDirective( preprocessor_, name, def ) );
}

void HeaderTracker::macroUndefined( llvm::StringRef name, clang::MacroDirective const * def )
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    commitMacros();
#ifdef DEBUG_HEADERS
    for ( unsigned int x = 0; x < fileStack_.size(); ++x )
        logging_stream << "    ";
    logging_stream << "Macro undefined: '" << name.str() << '\'' << std::endl;
#endif
    currentHeaderCtx().macroUndefined( MacroName( name ) );
}

void HeaderTracker::pragmaOnce()
{
    if ( !hasCurrentHeaderCtx() || cacheDisabled() || currentHeaderCtx().fromCache() )
        return;
    currentHeaderCtx().macroDefined( macroForPragmaOnce( *fileStack_.back().file ), MacroValue( " 1" ) );
}

void ConditionStack::ifDirective( clang::SourceLocation loc, bool taken )
{
#ifdef DEBUG_HEADERS
    logging_stream << "#if directive (" << ( taken ? "taken)" : "not taken)" ) << std::endl;
#endif
    conditions.emplace_back( loc );
    condition().macros.swap( macros );
    condition().lastBranchTaken = taken;
    if ( taken )
        condition().anyBranchTaken = true;
}

void ConditionStack::elifDirective( clang::SourceLocation loc, bool taken )
{
#ifdef DEBUG_HEADERS
    logging_stream << "#elif directive (" << (taken ? "taken)" : "not taken)" ) << std::endl;
#endif
    if ( empty() )
    {
        commit();
        return;
    }

    condition().macros.insert( condition().macros.end(), macros.begin(), macros.end() );
    macros.clear();
    if ( taken )
        condition().anyBranchTaken = true;
    if ( lastConditionSkippable( loc ) )
        condition().lastBranchTaken = taken;
}

void ConditionStack::elseDirective( clang::SourceLocation loc )
{
#ifdef DEBUG_HEADERS
    logging_stream << "#else directive" << std::endl;
#endif
    if ( empty() )
    {
        commit();
        return;
    }

    if ( !macros.empty() )
    {
        condition().macros.insert( condition().macros.end(), macros.begin(), macros.end() );
        macros.clear();
        // This was most likely caused by Clang not reporting an #elif
        // directive. Mark the whole #if-#elif-#else block as not-taken
        // so that it can be re-scanned.
        condition().lastBranchTaken = false;
    }

    if ( lastConditionSkippable( loc ) )
        condition().lastBranchTaken = !condition().anyBranchTaken;
}

void ConditionStack::endifDirective( clang::SourceLocation loc )
{
#ifdef DEBUG_HEADERS
    logging_stream << "#endif directive" << std::endl;
#endif
    if ( empty() )
    {
        assert( macros.empty() );
        return;
    }

    if ( !macros.empty() )
    {
        condition().macros.insert( condition().macros.end(), macros.begin(), macros.end() );
        macros.clear();
        // See above.
        condition().lastBranchTaken = false;
    }

    if ( lastConditionSkippable( loc ) )
    {
#ifdef DEBUG_HEADERS
        for ( llvm::StringRef str : condition().macros )
            logging_stream << "popping " << str.str() << std::endl;
#endif
        conditions.pop_back();
    }
#ifdef DEBUG_HEADERS
    else
    {
        logging_stream << "Block not skippable" << std::endl;
    }
#endif
}

bool ConditionStack::lastConditionSkippable( clang::SourceLocation loc )
{
    clang::SourceLocation begin = condition().lastLocation;
    condition().lastLocation = loc;
    if ( condition().lastBranchTaken || skippable( begin, loc ) )
        return true;
    commit();
    return false;
}

bool ConditionStack::skippable( clang::SourceLocation startLoc, clang::SourceLocation endLoc ) const
{
    clang::SourceManager & sourceManager( preprocessor_.getSourceManager() );
    assert( sourceManager.getFileID( startLoc ) == sourceManager.getFileID( endLoc ) );
    char const * begin = sourceManager.getCharacterData( startLoc );
    char const * end = sourceManager.getCharacterData( endLoc );
    std::size_t const contentSize( end - begin );
    tmpBuf_.reserve( contentSize + 1 );
    std::memcpy( tmpBuf_.data(), begin, contentSize );
    tmpBuf_.data()[ contentSize ] = '\0';

    // see if there are any #define or #include directives in the #if/#endif
    clang::Lexer lexer( startLoc, preprocessor_.getLangOpts(), tmpBuf_.data(), tmpBuf_.data(), tmpBuf_.data() + contentSize );
    clang::Token tok;
    while ( !lexer.LexFromRawLexer( tok ) )
    {
        if ( tok.isNot( clang::tok::hash ) || !tok.isAtStartOfLine() )
            continue;
        if ( lexer.LexFromRawLexer( tok ) )
            return true;
        if ( tok.isNot( clang::tok::raw_identifier ) )
            continue;

        llvm::StringRef const identifier( tok.getRawIdentifier() );
        if ( ( identifier == "define" ) || ( identifier == "undef" ) || ( identifier == "include" ) )
            return false;
    }
    return true;
}



#include "utility_.hpp"

#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/Preprocessor.h>

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

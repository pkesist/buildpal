#include "utility_.hpp"

#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/Preprocessor.h>

llvm::StringRef macroValueFromDirective( clang::Preprocessor const & preprocessor, llvm::StringRef const macroName, clang::MacroDirective const * def )
{
    assert( def );
    clang::MacroInfo const * macroInfo( def->getMacroInfo() );
    assert( macroInfo );
    assert( !macroInfo->isBuiltinMacro() );
    clang::SourceLocation const startLoc( macroInfo->getDefinitionLoc() );
    assert( !startLoc.isInvalid() );
    clang::SourceManager & sourceManager( preprocessor.getSourceManager() );
    std::pair<clang::FileID, unsigned> startSpellingLoc( sourceManager.getDecomposedSpellingLoc( startLoc ) );
    bool invalid;
    llvm::StringRef const buffer( sourceManager.getBufferData( startSpellingLoc.first, &invalid ) );
    assert( !invalid );
    char const * const macroStart = buffer.data() + startSpellingLoc.second;
    unsigned int const tokCount( macroInfo->getNumTokens() );
    llvm::StringRef result;
    if ( !tokCount )
    {
        // Macro does not have any tokens. I have no idea how to get the length
        // of the directive itself. Just go to the end of line and then back up
        // until the first character. In case we see a backslash, just ignore it
        // and keep backing up.
        char const * end = macroStart;
        while ( *end != '\n' ) ++end;
        --end;
        while ( ( *end == '\t' ) || ( *end == ' ' ) || ( *end == '\r' ) || ( *end == '\\' ) ) --end;
        result = llvm::StringRef( macroStart, end - macroStart + 1 );
    }
    else
    {
        clang::Token const & lastToken( macroInfo->getReplacementToken( tokCount - 1 ) );
        clang::SourceLocation const endLoc( lastToken.getLocation() );
        std::pair<clang::FileID, unsigned> endSpellingLoc( sourceManager.getDecomposedSpellingLoc( endLoc ) );
        endSpellingLoc.second += lastToken.getLength();
        assert( startSpellingLoc.first == endSpellingLoc.first );
        assert( startSpellingLoc.second <= endSpellingLoc.second );
        result = llvm::StringRef( macroStart, endSpellingLoc.second - startSpellingLoc.second );
    }
    // Result starts with macro name, skip that.
    return llvm::StringRef( result.data() + macroName.size(), result.size() - macroName.size() );
}

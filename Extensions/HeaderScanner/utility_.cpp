#include "utility_.hpp"

#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Lex/Preprocessor.h>

#include <codecvt>

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

static bool const systemIsLittleEndian = true;

llvm::MemoryBuffer * convertEncodingIfNeeded( llvm::MemoryBuffer * pMemoryBuffer )
{
    // Clang supports UTF-8 only. We also want to support UTF-16.
    llvm::StringRef const data = pMemoryBuffer->getBuffer();

    bool const bigEndian( data.startswith("\xFE\xFF") );
    bool const littleEndian( data.startswith("\xFF\xFE") );
    if ( !bigEndian && !littleEndian )
        return NULL;

    wchar_t const * start = reinterpret_cast<wchar_t const *>( data.data() + 2 );
    std::size_t const inputSize = ( data.size() - 2 ) / sizeof(wchar_t);
    std::vector<wchar_t> input( start, start + inputSize );

    // This can be written more tersly, but exactly one of these branches
    // is redundant, so try to make it easy for the optimizer.
    if ( littleEndian )
    {
        for ( wchar_t & stride : input )
        {
            char const * bytePtr = reinterpret_cast<char const *>( &stride );
            stride = static_cast<wchar_t>( ( bytePtr[1] << 8 ) | bytePtr[0] );
        }
    }
    else
    {
        for ( wchar_t & stride : input )
        {
            char const * bytePtr = reinterpret_cast<char const *>( &stride );
            stride = static_cast<wchar_t>( ( bytePtr[0] << 8 ) | bytePtr[1] );
        }
    }
    std::wstring_convert<
        std::codecvt_utf8_utf16<wchar_t>
    > converter;
    std::string utf8( converter.to_bytes( &input[0], &input[0] + input.size() ) );
    utf8.push_back('\0');
    return llvm::MemoryBuffer::getMemBufferCopy( utf8, "" );
}

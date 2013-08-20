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
    char const * defLoc( buffer->getBufferStart() + spellingLoc.second );
    // Find end of directive.
    char const * end( defLoc );
    bool lastNonspaceIsBackslash( false );
    bool lastIsSpace( false );
    for ( ; ; ++end )
    {
        if ( *end == '\n' && !lastNonspaceIsBackslash )
            break;
        bool const currentIsSpace = *end == ' ' || *end == '\t' || *end == '\r';
        if ( !currentIsSpace )
            lastNonspaceIsBackslash = ( !lastNonspaceIsBackslash || lastIsSpace ) && ( *end == '\\' );
        lastIsSpace = currentIsSpace;
    }
    while ( *end == ' ' || *end == '\t' || *end == '\r' )
        end--;
    return llvm::StringRef( defLoc, end - defLoc );
}

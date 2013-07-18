//------------------------------------------------------------------------------
#include "headerScanner_.hpp"
#include "headerTracker_.hpp"

#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/DiagnosticOptions.h"
#include "clang/Basic/MacroBuilder.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Basic/TokenKinds.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Basic/FileManager.h"
#include "clang/Frontend/PreprocessorOutputOptions.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Frontend/Utils.h"
#include "clang/Lex/HeaderSearch.h"
#include "clang/Lex/HeaderSearchOptions.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/PreprocessorOptions.h"
#include "clang/Rewrite/Frontend/Rewriters.h"
#include "llvm/Config/config.h"
#include "llvm/Support/Host.h"
#include "llvm/Support/MemoryBuffer.h"

#include <iostream>

namespace
{
    class HeaderScanner : public clang::PPCallbacks
    {
    public:
        explicit HeaderScanner
        (
            HeaderTracker & headerTracker,
            clang::SourceManager & sourceManager,
            clang::Preprocessor & preprocessor,
            clang::FileManager & fileManager,
            PreprocessingContext::IgnoredHeaders const & ignoredHeaders,
            Preprocessor::HeaderRefs & includedHeaders
        )
            :
            headerTracker_            ( headerTracker   ),
            sourceManager_            ( sourceManager   ),
            preprocessor_             ( preprocessor    ),
            fileManager_              ( fileManager     ),
            headers_                  ( includedHeaders ),
            ignoredHeaders_           ( ignoredHeaders  ),
            foundViaFileStillNotFound_( false           )
        {
        }

        virtual ~HeaderScanner() {}

        virtual void FileStillNotFound(clang::SourceLocation FilenameLoc,
            llvm::StringRef filename, bool isAngled,
            clang::DirectoryLookup const * fromDir,
            clang::DirectoryLookup const * & curDir,
            clang::FileEntry const * & file)
        {
            headerTracker_.findFile( filename, isAngled, file );
            if ( file )
            {
                includeFilename_ = filename;
                foundViaFileStillNotFound_ = true;
            }
        }

        virtual void FileChanged( clang::SourceLocation loc, FileChangeReason reason,
            clang::SrcMgr::CharacteristicKind, clang::FileID exitedFID )
        {
            if ( reason == EnterFile )
            {
                foundViaFileStillNotFound_ = false;
                clang::FileID const fileId( sourceManager_.getFileID( loc ) );
                clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
                if ( !fileEntry )
                    return;
                if ( fileId == sourceManager_.getMainFileID() )
                    headerTracker_.enterSourceFile( fileEntry );
                else
                    headerTracker_.enterHeader( includeFilename_ );
            }
            else if ( reason == ExitFile )
            {
                clang::FileID const fileId( exitedFID );
                clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
                if ( !fileEntry )
                    return;
                headerTracker_.leaveHeader( ignoredHeaders_ );
            }
        }

        virtual void EndOfMainFile()
        {
            headers_ = headerTracker_.exitSourceFile();
        }

        virtual void FileSkipped
        (
            clang::FileEntry const & fileEntry,
            clang::Token const &,
            clang::SrcMgr::CharacteristicKind
        )
        {
            foundViaFileStillNotFound_ = false;
            headerTracker_.headerSkipped( includeFilename_ );
        }

        virtual void InclusionDirective
        (
            clang::SourceLocation loc, clang::Token const &,
            clang::StringRef fileName, bool IsAngled,
            clang::CharSourceRange filenameRange, clang::FileEntry const * fileEntry,
            clang::StringRef searchPath, clang::StringRef relativePath,
            clang::Module const * imported
        )
        {
            assert( !fileEntry || foundViaFileStillNotFound_ );
        }

        virtual void MacroExpands( clang::Token const & macroNameTok, clang::MacroDirective const * md, clang::SourceRange, clang::MacroArgs const * )
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void MacroDefined( clang::Token const & macroNameTok, clang::MacroDirective const * md )
        {
            headerTracker_.macroDefined( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void MacroUndefined( clang::Token const & macroNameTok, clang::MacroDirective const * md )
        {
            headerTracker_.macroUndefined( macroNameTok.getIdentifierInfo()->getName(), md );
        }

        virtual void Defined( clang::Token const & macroNameTok, clang::MacroDirective const * md )
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void Ifdef(clang::SourceLocation Loc, clang::Token const & macroNameTok, clang::MacroDirective const * md )
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void Ifndef(clang::SourceLocation Loc, clang::Token const & macroNameTok, clang::MacroDirective const * md )
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

    private:
        HeaderTracker & headerTracker_;
        clang::SourceManager & sourceManager_;
        clang::Preprocessor & preprocessor_;
        clang::FileManager & fileManager_;
        Preprocessor::HeaderRefs & headers_;
        PreprocessingContext::IgnoredHeaders const & ignoredHeaders_;
        clang::StringRef includeFilename_;
        bool foundViaFileStillNotFound_;
    };
}  // anonymous namespace

Preprocessor::Preprocessor()
{
    // Create diagnostics.
    compiler().createDiagnostics( new clang::IgnoringDiagConsumer() );

    // Create target info.
    clang::CompilerInvocation * invocation = new clang::CompilerInvocation();
    invocation->getTargetOpts().Triple = llvm::sys::getDefaultTargetTriple();
    compiler().setInvocation( invocation );
    compiler().setTarget(clang::TargetInfo::CreateTargetInfo(
        compiler().getDiagnostics(), &compiler().getTargetOpts()));

    clang::CompilerInvocation::setLangDefaults(
        compiler().getLangOpts(), clang::IK_CXX);

    // Configure the include paths.
    clang::HeaderSearchOptions &hsopts = compiler().getHeaderSearchOpts();
    hsopts.UseBuiltinIncludes = false;
    hsopts.UseStandardSystemIncludes = false;
    hsopts.UseStandardCXXIncludes = false;

    // Create the file manager.
    compiler().createFileManager();

    // Create the source manager.
    sourceManager_.reset( new clang::SourceManager( compiler().getDiagnostics(), compiler().getFileManager(), false ) );
    compiler().setSourceManager( &sourceManager() );
    headerTracker_.reset( new HeaderTracker( sourceManager() ) );
}

void Preprocessor::setupPreprocessor( PreprocessingContext const & ppc, std::string const & filename )
{
    sourceManager().clearIDTables();
    clang::FileEntry const * mainFileEntry = compiler().getFileManager().getFile( filename );
    if ( !mainFileEntry )
        throw std::runtime_error( "Could not find source file." );
    sourceManager().createMainFileID( mainFileEntry );

    // Setup new preprocessor instance.
    compiler().createPreprocessor();
    clang::HeaderSearch & headers = preprocessor().getHeaderSearchInfo();
    
    std::vector<clang::DirectoryLookup> dirs;
    headers.SetSearchPaths(dirs, 0, 0, true);

    // Setup predefines.
    //   Clang always tries to define some macros, even if UsePredefines is off,
    // so we cheat.
    //std::string predefines( preprocessor().getPredefines() );
    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::const_iterator iter( ppc.defines().begin() ); iter != ppc.defines().end(); ++iter )
        macroBuilder.defineMacro( iter->first, iter->second );
    preprocessor().setPredefines( predefinesStream.str() );
}

clang::HeaderSearch * Preprocessor::getHeaderSearch( PreprocessingContext::SearchPath const & searchPath )
{
    clang::HeaderSearch * headerSearch( new clang::HeaderSearch(
        &compiler().getHeaderSearchOpts(),
        compiler().getFileManager(),
        compiler().getDiagnostics(),
        compiler().getLangOpts(),
        &compiler().getTarget()));

    // Setup search path.
    for ( PreprocessingContext::SearchPath::const_iterator iter( searchPath.begin() ); iter != searchPath.end(); ++iter )
    {
        std::string const & path = iter->first;
        bool const sysinclude = iter->second;
        clang::DirectoryEntry const * entry = compiler().getFileManager().getDirectory( llvm::StringRef( path.c_str(), path.size() ) );
        clang::DirectoryLookup lookup( entry, sysinclude ? clang::SrcMgr::C_System : clang::SrcMgr::C_User, false );
        headerSearch->AddSearchPath( lookup, true );
    }

    return headerSearch;
}

Preprocessor::HeaderRefs Preprocessor::scanHeaders( PreprocessingContext const & ppc, std::string const & filename, std::string const & pth )
{
    clang::PreprocessorOptions & ppOpts( compiler().getPreprocessorOpts() );
    struct TokenCacheSetter
    {
        TokenCacheSetter( std::string & tc, std::string const & pth )
            : tc_( tc ) { tc_ = pth; }

        ~TokenCacheSetter() { tc_.clear(); }

        std::string & tc_;
    } tokenCacheSetter( ppOpts.TokenCache, pth );

    setupPreprocessor( ppc, filename );
    struct DiagnosticsSetup
    {
        DiagnosticsSetup( clang::DiagnosticConsumer & client,
            clang::LangOptions const & opts,
            clang::Preprocessor & preprocessor )
            : client_( client )
        {
            client_.BeginSourceFile( opts, &preprocessor );
        }

        ~DiagnosticsSetup() { client_.EndSourceFile(); }

        clang::DiagnosticConsumer & client_;
    } const diagnosticsGuard
    (
        *compiler().getDiagnostics().getClient(),
        compiler().getLangOpts(), preprocessor()
    );

    HeaderRefs result;
    headerTracker().setPreprocessor( &preprocessor() );
    headerTracker().setHeaderSearch( getHeaderSearch( ppc.searchPath() ) );

    preprocessor().addPPCallbacks( new HeaderScanner( headerTracker(),
        sourceManager(), preprocessor(), compiler().getFileManager(),
        ppc.ignoredHeaders(), result ) );
    preprocessor().SetMacroExpansionOnlyInDirectives();

    preprocessor().EnterMainSourceFile();
    while ( true )
    {
        clang::Token token;
        preprocessor().LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    preprocessor().EndSourceFile();
    compiler().getFileManager().clearStatCaches();
    headerTracker().setPreprocessor( 0 );

    return result;
}


std::string & Preprocessor::preprocess( PreprocessingContext const & ppc,
    std::string const & filename, std::string & output )
{
    llvm::raw_string_ostream os( output );
    setupPreprocessor( ppc, filename );
    clang::PreprocessorOutputOptions & preprocessorOutputOptions( compiler().getPreprocessorOutputOpts() );
    preprocessorOutputOptions.ShowCPP = 1;
    preprocessorOutputOptions.ShowLineMarkers = 1;
    preprocessorOutputOptions.ShowMacroComments = 1;
    preprocessorOutputOptions.ShowMacros = 0;
    preprocessorOutputOptions.RewriteIncludes = 0;

    clang::DoPrintPreprocessedInput( preprocessor(), &os, preprocessorOutputOptions );
    return os.str();
}

std::string & Preprocessor::rewriteIncludes( PreprocessingContext const & ppc, std::string const & filename, std::string & output )
{
    llvm::raw_string_ostream os( output );
    setupPreprocessor( ppc, filename );
    clang::PreprocessorOutputOptions & preprocessorOutputOptions( compiler().getPreprocessorOutputOpts() );
    preprocessorOutputOptions.ShowCPP = 1;
    preprocessorOutputOptions.ShowLineMarkers = 1;
    preprocessorOutputOptions.ShowMacroComments = 1;
    preprocessorOutputOptions.ShowMacros = 0;
    preprocessorOutputOptions.RewriteIncludes = 1;

    clang::RewriteIncludesInInput( preprocessor(), &os, preprocessorOutputOptions );
    return os.str();
}


void Preprocessor::emitPTH( PreprocessingContext const & ppc, std::string const & filename, std::string const & outputFile )
{
    setupPreprocessor( ppc, filename );
    std::string error;
    llvm::raw_fd_ostream output( outputFile.c_str(), error, llvm::raw_fd_ostream::F_Binary );
    if ( !error.empty() )
        throw std::runtime_error( error );
    clang::CacheTokens( preprocessor(), &output );
}


//------------------------------------------------------------------------------

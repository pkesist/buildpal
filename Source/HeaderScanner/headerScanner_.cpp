//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/DiagnosticOptions.h"
#include "clang/Basic/MacroBuilder.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Basic/TokenKinds.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Basic/FileManager.h"
#include "clang/Frontend/FrontendDiagnostic.h"
#include "clang/Lex/HeaderSearch.h"
#include "clang/Lex/HeaderSearchOptions.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/PreprocessorOptions.h"
#include "llvm/Config/config.h"
#include "llvm/Support/Host.h"

#include <set>
#include <string>
#include <iostream>

namespace
{
    class FileChangeCallback : public clang::PPCallbacks
    {
    public:
        explicit FileChangeCallback
        (
            clang::SourceManager const & sourceManager,
            clang::Preprocessor & preprocessor,
            Preprocessor::HeaderRefs & headers
        )
            :
            sourceManager_( sourceManager ),
            preprocessor_ ( preprocessor  ),
            headers_      ( headers       )
        {
        }

        virtual ~FileChangeCallback() {}

        virtual void FileChanged(clang::SourceLocation Loc, FileChangeReason Reason,
            clang::SrcMgr::CharacteristicKind FileType, clang::FileID PrevFID = clang::FileID())
        {
            if ( Reason != EnterFile )
                return;
            clang::FileID const fileId( sourceManager_.getFileID( Loc ) );
            if ( fileId == sourceManager_.getMainFileID() )
                return;
            clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
            if ( fileEntry )
            {
                headers_.insert( std::make_pair( lastRelativePath_, fileEntry->getName() ) );
            }
        }

        virtual void InclusionDirective
        (
            clang::SourceLocation, clang::Token const &,
            clang::StringRef fileName, bool IsAngled,
            clang::CharSourceRange filenameRange, clang::FileEntry const * file,
            clang::StringRef searchPath, clang::StringRef relativePath,
            clang::Module const * imported
        )
        {
            lastRelativePath_ = relativePath;
        }

        virtual void MacroExpands
        (
            clang::Token const & macroNameTok, clang::MacroDirective const *,
            clang::SourceRange Range, MacroArgs const *
        )
        {
            preprocessor_.CurPPLexer->ParsingFilename;
        }

    private:
        clang::SourceManager const & sourceManager_;
        clang::Preprocessor & preprocessor_;
        Preprocessor::HeaderRefs & headers_;
        clang::StringRef lastRelativePath_;
    };
}  // anonymous namespace

Preprocessor::Preprocessor()
{
    // Create diagnostics.
    compiler().createDiagnostics( new clang::IgnoringDiagConsumer() );

#if 0
    // Do not use Clang predefines.
    // TODO: This does not work well, Clang still defines some symbols.
    // We remove these manually, see below (setPredefines).
    clang::PreprocessorOptions & preprocessorOptions( compiler().getInvocation().getPreprocessorOpts() );
    preprocessorOptions.UsePredefines = false;
#endif

    // Create target info.
    clang::TargetOptions target_options;
    target_options.Triple = llvm::sys::getDefaultTargetTriple();
    compiler().setTarget(clang::TargetInfo::CreateTargetInfo(
        compiler().getDiagnostics(), &target_options));

    clang::CompilerInvocation::setLangDefaults(
        compiler().getLangOpts(), clang::IK_CXX);

    // Configure the include paths.
    clang::HeaderSearchOptions &hsopts = compiler().getHeaderSearchOpts();
    hsopts.UseBuiltinIncludes = false;
    hsopts.UseStandardSystemIncludes = false;
    hsopts.UseStandardCXXIncludes = false;

    // Create the file manager.
    compiler().createFileManager();
}

Preprocessor::HeaderRefs Preprocessor::scanHeaders( PreprocessingContext & ppc, std::string const & filename )
{
    // Setup source manager.
    if ( !compiler().hasSourceManager() )
    {
        compiler().createSourceManager( compiler().getFileManager() );
    }
    else
    {
        compiler().getSourceManager().clearIDTables();
    }
    clang::FileEntry const * mainFileEntry = compiler().getFileManager().getFile( filename );
    compiler().getSourceManager().createMainFileID( mainFileEntry );

    // Setup new preprocessor instance.
    compiler().createPreprocessor();
    clang::Preprocessor & preprocessor = compiler().getPreprocessor();
    clang::HeaderSearch & headers = preprocessor.getHeaderSearchInfo();

    preprocessor.SetSuppressIncludeNotFoundError( true );

    // Setup search path.
    for ( PreprocessingContext::SearchPath::const_iterator iter( ppc.searchPath().begin() ); iter != ppc.searchPath().end(); ++iter )
    {
        std::string const & path = iter->first;
        bool const sysinclude = iter->second;
        clang::DirectoryEntry const * entry = compiler().getFileManager().getDirectory( llvm::StringRef( path.c_str(), path.size() ) );
        clang::DirectoryLookup lookup( entry, sysinclude ? clang::SrcMgr::C_System : clang::SrcMgr::C_User, false );
        headers.AddSearchPath( lookup, true );
    }

    // Setup predefines.
    //   Clang always tries to define some macros, even if UsePredefines is off,
    // so we cheat.
    //std::string predefines( preprocessor.getPredefines() );
    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::const_iterator iter( ppc.defines().begin() ); iter != ppc.defines().end(); ++iter )
        macroBuilder.defineMacro( iter->first, iter->second );
    preprocessor.setPredefines( predefinesStream.str() );

    struct DiagnosticsGuard
    {
        DiagnosticsGuard( clang::DiagnosticConsumer & client, clang::LangOptions const & opts, clang::Preprocessor & preprocessor )
            :
            client_( client )
        {
            client_.BeginSourceFile( opts, &preprocessor );
        }

        ~DiagnosticsGuard()
        {
            client_.EndSourceFile();
        }

        clang::DiagnosticConsumer & client_;
    } const diagnosticsGuard( *compiler().getDiagnostics().getClient(), compiler().getLangOpts(), preprocessor );

    HeaderRefs result;
    preprocessor.addPPCallbacks( new FileChangeCallback( compiler().getSourceManager(), preprocessor, result ) );

    preprocessor.EnterMainSourceFile();
    while ( true )
    {
        clang::Token token;
        preprocessor.LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    return result;
}




//------------------------------------------------------------------------------

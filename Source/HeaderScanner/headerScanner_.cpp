//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

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
#include "llvm/Config/config.h"
#include "llvm/Support/Host.h"
#include "llvm/Support/raw_ostream.h"

#include <set>
#include <string>
#include <iostream>

#include <windows.h>
#undef SearchPath
namespace
{
    class FileChangeCallback : public clang::PPCallbacks
    {
    public:
        explicit FileChangeCallback
        (
            clang::SourceManager const & sourceManager,
            clang::Preprocessor & preprocessor,
            Preprocessor::HeaderRefs & includedHeaders,
            Preprocessor::HeaderList const & headersToIgnore
        )
            :
            sourceManager_  ( sourceManager   ),
            preprocessor_   ( preprocessor    ),
            headers_        ( includedHeaders ),
            headersToIgnore_( headersToIgnore )
        {
        }

        virtual ~FileChangeCallback() {}

        virtual void FileChanged(clang::SourceLocation Loc, FileChangeReason Reason,
            clang::SrcMgr::CharacteristicKind FileType, clang::FileID PrevFID = clang::FileID())
        {
            if ( Reason == EnterFile )
            {
                if ( sourceManager_.getFileCharacteristic( Loc ) == clang::SrcMgr::C_System )
                    return;
                clang::FileID const fileId( sourceManager_.getFileID( Loc ) );
                if ( headersToIgnore_.find( includeFilename_ ) != headersToIgnore_.end() )
                {
                    ignoringFID_ = fileId;
                    return;
                }
                if ( fileId == sourceManager_.getMainFileID() )
                    return;
                clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
                if ( fileEntry )
                {
                    if ( ignoring() )
                    {
                        ignoredHeaders_.insert( std::make_pair( includeFilename_, fileEntry->getName() ) );
                    }
                    else
                    {
                        headers_.insert( std::make_pair( includeFilename_, fileEntry->getName() ) );
                    }
                }
            }
            else if ( Reason == ExitFile )
            {
                if ( !ignoring() )
                    return;
                clang::FileID const fileId( sourceManager_.getFileID( Loc ) );
                if ( ignoringFID_ == fileId )
                    ignoringFID_ = clang::FileID();
            }
        }

        virtual void FileSkipped
        (
            clang::FileEntry const & parentFile,
		    clang::Token const & filenameTok,
		    clang::SrcMgr::CharacteristicKind fileType
        )
        {
            if ( ignoring() )
                return;
            IgnoredHeaders::iterator const iter( ignoredHeaders_.find( includeFilename_ ) );
            if ( iter != ignoredHeaders_.end() )
            {
                headers_.insert( *iter );
                ignoredHeaders_.erase( iter );
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
            includeFilename_ = relativePath;
        }

    private:
        bool ignoring() const { return !ignoringFID_.isInvalid(); }

    private:
        typedef std::map<std::string, std::string> IgnoredHeaders;

    private:
        clang::SourceManager const & sourceManager_;
        clang::Preprocessor & preprocessor_;
        Preprocessor::HeaderRefs & headers_;
        Preprocessor::HeaderList const & headersToIgnore_;
        IgnoredHeaders ignoredHeaders_;
        clang::FileID ignoringFID_;
        clang::StringRef includeFilename_;
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
}

void Preprocessor::setupPreprocessor( PreprocessingContext const & ppc, std::string const & filename )
{
    // Setup source manager.
    if ( compiler().hasSourceManager() )
        compiler().getSourceManager().clearIDTables();
    else
        compiler().createSourceManager( compiler().getFileManager() );
    clang::FileEntry const * mainFileEntry = compiler().getFileManager().getFile( filename );
    if ( !mainFileEntry )
        throw std::runtime_error( "Could not find source file." );
    compiler().getSourceManager().createMainFileID( mainFileEntry );

    // Setup new preprocessor instance.
    compiler().createPreprocessor();
    clang::HeaderSearch & headers = preprocessor().getHeaderSearchInfo();

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
    //std::string predefines( preprocessor().getPredefines() );
    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::const_iterator iter( ppc.defines().begin() ); iter != ppc.defines().end(); ++iter )
        macroBuilder.defineMacro( iter->first, iter->second );
    preprocessor().setPredefines( predefinesStream.str() );
}

Preprocessor::HeaderRefs Preprocessor::scanHeaders( PreprocessingContext const & ppc, std::string const & filename, HeaderList const & headersToSkip, std::string const & pth )
{
    clang::PreprocessorOptions & ppOpts( compiler().getPreprocessorOpts() );
    struct TokenCacheSetter
    {
        TokenCacheSetter( std::string & tc, std::string const & pth ) : tc_( tc )
        {
            tc_ = pth;
        }
        ~TokenCacheSetter()
        {
            tc_.clear();
        }
        std::string & tc_;
    } tokenCacheSetter( ppOpts.TokenCache, pth );

    setupPreprocessor( ppc, filename );
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
    } const diagnosticsGuard( *compiler().getDiagnostics().getClient(), compiler().getLangOpts(), preprocessor() );

    HeaderRefs result;
    preprocessor().addPPCallbacks( new FileChangeCallback( compiler().getSourceManager(), preprocessor(), result, headersToSkip ) );
    preprocessor().SetMacroExpansionOnlyInDirectives();

    preprocessor().EnterMainSourceFile();
    while ( true )
    {
        clang::Token token;
        preprocessor().LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    compiler().getFileManager().clearStatCaches();
    return result;
}


std::string & Preprocessor::preprocess( PreprocessingContext const & ppc, std::string const & filename, std::string & output )
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

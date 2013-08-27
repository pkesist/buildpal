//------------------------------------------------------------------------------
#include "headerScanner_.hpp"
#include "headerTracker_.hpp"

#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/DiagnosticOptions.h"
#include "clang/Basic/FileSystemStatCache.h"
#include "clang/Basic/MacroBuilder.h"
#include "clang/Basic/TargetInfo.h"
#include "clang/Basic/TokenKinds.h"
#include "clang/Basic/SourceManager.h"
#include "clang/Basic/FileManager.h"
#include "clang/Frontend/PreprocessorOutputOptions.h"
#include "clang/Frontend/FrontendActions.h"
#include "clang/Frontend/TextDiagnosticBuffer.h"
#include "clang/Frontend/Utils.h"
#include "clang/Lex/HeaderSearch.h"
#include "clang/Lex/HeaderSearchOptions.h"
#include "clang/Lex/Preprocessor.h"
#include "clang/Lex/PreprocessorOptions.h"
#include "clang/Rewrite/Frontend/Rewriters.h"
#include "llvm/Config/config.h"
#include "llvm/Support/Host.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/ADT/SmallString.h"

#include <iostream>

namespace
{
    class HeaderScanner : public clang::PPCallbacks
    {
    public:
        explicit HeaderScanner
        (
            HeaderTracker & headerTracker,
            clang::Preprocessor & preprocessor,
            PreprocessingContext::IgnoredHeaders const & ignoredHeaders,
            Preprocessor::HeaderRefs & includedHeaders
        )
            :
            headerTracker_ ( headerTracker   ),
            preprocessor_  ( preprocessor    ),
            headers_       ( includedHeaders ),
            ignoredHeaders_( ignoredHeaders  )
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
                includeFilename_ = filename;
        }

        virtual void FileChanged( clang::SourceLocation loc, FileChangeReason reason,
            clang::SrcMgr::CharacteristicKind, clang::FileID exitedFID )
        {
            if ( reason == EnterFile )
            {
                clang::FileID const fileId( preprocessor_.getSourceManager().getFileID( loc ) );
                clang::FileEntry const * const fileEntry( preprocessor_.getSourceManager().getFileEntryForID( fileId ) );
                if ( !fileEntry )
                    return;
                if ( fileId == preprocessor_.getSourceManager().getMainFileID() )
                    headerTracker_.enterSourceFile( fileEntry );
                else
                    headerTracker_.enterHeader( includeFilename_ );
            }
            else if ( reason == ExitFile )
            {
                clang::FileID const fileId( exitedFID );
                clang::FileEntry const * const fileEntry( preprocessor_.getSourceManager().getFileEntryForID( fileId ) );
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
            headerTracker_.headerSkipped( includeFilename_ );
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
        clang::Preprocessor & preprocessor_;
        Preprocessor::HeaderRefs & headers_;
        PreprocessingContext::IgnoredHeaders const & ignoredHeaders_;
        clang::StringRef includeFilename_;
    };

    class DiagnosticConsumer : public clang::DiagnosticConsumer
    {
        virtual void HandleDiagnostic(
            clang::DiagnosticsEngine::Level level,
            clang::Diagnostic const & info) 
        {
            clang::DiagnosticConsumer::HandleDiagnostic( level, info );
            //llvm::SmallString<100> buffer;
            //info.FormatDiagnostic( buffer );
            //switch ( level )
            //{
            //    case clang::DiagnosticsEngine::Note: std::cout << "Note: " << buffer.str().str() << '\n'; break;
            //    case clang::DiagnosticsEngine::Warning: std::cout << "Warning: " << buffer.str().str() << '\n'; break;
            //    case clang::DiagnosticsEngine::Error: std::cout << "Error: " << buffer.str().str() << '\n'; break;
            //    case clang::DiagnosticsEngine::Fatal: std::cout << "Fatal: " << buffer.str().str() << '\n'; break;
            //}
        }
    };

    struct DoNotOpenFiles : public clang::MemorizeStatCalls
    {
        virtual LookupResult getStat
        (
            const char * path,
            struct stat & statBuf,
            bool isFile,
            int * FileDescriptor
        )
        {
            return clang::MemorizeStatCalls::getStat( path, statBuf, isFile, 0 );
        };
    };
}  // anonymous namespace

Preprocessor::Preprocessor( Cache * cache )
    : cache_( cache )
{
    // Create diagnostics.
    compiler().createDiagnostics( new DiagnosticConsumer() );

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
    hsopts.Sysroot.clear();

    compiler().createFileManager();
    compiler().getFileManager().addStatCache( new DoNotOpenFiles() );
}

void Preprocessor::setupPreprocessor( PreprocessingContext const & ppc, std::string const & filename )
{
    if ( compiler().hasSourceManager() )
        compiler().getSourceManager().clearIDTables();
    else
        compiler().createSourceManager( compiler().getFileManager() );

    clang::FileEntry const * mainFileEntry = compiler().getFileManager().getFile( filename );
    if ( !mainFileEntry )
        throw std::runtime_error( "Could not find source file." );
    sourceManager().createMainFileID( mainFileEntry );

    // Setup new preprocessor instance.
    compiler().createPreprocessor();
    clang::HeaderSearch & headers = preprocessor().getHeaderSearchInfo();
    
    std::vector<clang::DirectoryLookup> dirs;
    headers.SetSearchPaths( dirs, 0, 0, true );

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
    preprocessor().SetSuppressIncludeNotFoundError( true );
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

Preprocessor::HeaderRefs Preprocessor::scanHeaders( PreprocessingContext const & ppc, std::string const & filename )
{
    clang::PreprocessorOptions & ppOpts( compiler().getPreprocessorOpts() );
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

    // Do not let #pragma once interfere with cache.
    preprocessor().setPragmasEnabled( false );
    preprocessor().SetMacroExpansionOnlyInDirectives();

    HeaderTracker headerTracker( preprocessor(), *getHeaderSearch( ppc.searchPath() ), cache_ );
    preprocessor().addPPCallbacks( new HeaderScanner( headerTracker,
        preprocessor(), ppc.ignoredHeaders(), result ) );

    preprocessor().EnterMainSourceFile();
    if ( compiler().getDiagnostics().hasFatalErrorOccurred() )
    {
        return result;
    }
    while ( true )
    {
        clang::Token token;
        preprocessor().LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    preprocessor().EndSourceFile();
    return result;
}


//------------------------------------------------------------------------------

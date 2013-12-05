//------------------------------------------------------------------------------
#include "headerScanner_.hpp"
#include "headerTracker_.hpp"

#include <clang/Basic/Diagnostic.h>
#include <clang/Basic/DiagnosticOptions.h>
#include <clang/Basic/FileSystemStatCache.h>
#include <clang/Basic/MacroBuilder.h>
#include <clang/Basic/TargetInfo.h>
#include <clang/Basic/TokenKinds.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Basic/FileManager.h>
#include <clang/Frontend/PreprocessorOutputOptions.h>
#include <clang/Frontend/FrontendActions.h>
#include <clang/Frontend/TextDiagnosticBuffer.h>
#include <clang/Frontend/Utils.h>
#include <clang/Lex/HeaderSearch.h>
#include <clang/Lex/HeaderSearchOptions.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/PreprocessorOptions.h>
#include <clang/Rewrite/Frontend/Rewriters.h>
#include <llvm/Config/config.h>
#include <llvm/Support/Host.h>
#include <llvm/Support/Path.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/ADT/SmallString.h>

#include <iostream>

namespace
{
    class HeaderScanner : public clang::PPCallbacks
    {
    public:
        explicit HeaderScanner
        (
            HeaderTracker & headerTracker,
            llvm::StringRef filename,
            clang::Preprocessor & preprocessor,
            IgnoredHeaders const & ignoredHeaders,
            Headers & includedHeaders
        )
            :
            headerTracker_ ( headerTracker   ),
            preprocessor_  ( preprocessor    ),
            headers_       ( includedHeaders ),
            ignoredHeaders_( ignoredHeaders  ),
            filename_      ( filename        )
        {
        }

        virtual ~HeaderScanner() {}

        virtual void InclusionDirective(
            clang::SourceLocation hashLoc,
            clang::Token const & includeTok,
            llvm::StringRef fileName,
            bool IsAngled,
            clang::CharSourceRange filenameRange,
            clang::FileEntry const * file,
            llvm::StringRef SearchPath,
            llvm::StringRef RelativePath,
            clang::Module const * imported)
        {
            headerTracker_.inclusionDirective( SearchPath, RelativePath, file );
        }

        virtual void ReplaceFile( clang::FileEntry const * & file ) override
        {
            headerTracker_.replaceFile( file );
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
                    headerTracker_.enterSourceFile( fileEntry, filename_ );
                else
                    headerTracker_.enterHeader();
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
            headerTracker_.headerSkipped();
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
        llvm::StringRef filename_;
        Headers & headers_;
        IgnoredHeaders const & ignoredHeaders_;
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

    struct MemorizeStatCalls_PreventOpenFile : public clang::MemorizeStatCalls
    {
        // Prevent FileManager, HeaderSearch et al. to open files
        // unexpectedly.
        virtual clang::MemorizeStatCalls::LookupResult
            getStat( char const * path, clang::FileData & fileData, bool isFile,
            int * )
        {
            return clang::MemorizeStatCalls::getStat( path, fileData, isFile, 0 );
        }
    };
}  // anonymous namespace

clang::TargetOptions * createTargetOptions()
{
    clang::TargetOptions * result = new clang::TargetOptions();
    result->Triple = llvm::sys::getDefaultTargetTriple();
    return result;
}

Preprocessor::Preprocessor( Cache * cache )
    :
    diagID_       ( new clang::DiagnosticIDs() ),
    diagEng_      ( new clang::DiagnosticsEngine( diagID_, &diagOpts_ ) ),
    ppOpts_       ( new clang::PreprocessorOptions() ),
    langOpts_     ( new clang::LangOptions() ),
    targetOpts_   ( createTargetOptions() ),
    targetInfo_   ( clang::TargetInfo::CreateTargetInfo( *diagEng_, &*targetOpts_) ),
    hsOpts_       ( new clang::HeaderSearchOptions() ),
    fileManager_  ( fsOpts_ ),
    sourceManager_( *diagEng_, fileManager_, false ),
    headerSearch_ ( hsOpts_, sourceManager_, *diagEng_, *langOpts_, &*targetInfo_ ),
    cache_( cache )
{
    diagEng_->setClient( new DiagnosticConsumer() );
   
    // Configure the include paths.
    hsOpts_->UseBuiltinIncludes = false;
    hsOpts_->UseStandardSystemIncludes = false;
    hsOpts_->UseStandardCXXIncludes = false;
    hsOpts_->Sysroot.clear();

    fileManager_.addStatCache( new MemorizeStatCalls_PreventOpenFile() );
}

void Preprocessor::setupPreprocessor( PreprocessingContext const & ppc, llvm::StringRef filename )
{
    sourceManager_.clearIDTables();
    clang::FileEntry const * mainFileEntry = fileManager().getFile( filename );
    if ( !mainFileEntry )
        throw std::runtime_error( "Could not find source file." );
    sourceManager().createMainFileID( mainFileEntry );

    // Setup search path.
    headerSearch_.ClearFileInfo();
    std::vector<clang::DirectoryLookup> empty;
    headerSearch_.SetSearchPaths( empty, 0, 0, false );
    
    for ( auto const & searchPath : ppc.searchPath() )
    {
        std::string const & path = searchPath.first;
        bool const sysinclude = searchPath.second;
        clang::DirectoryEntry const * entry = fileManager().getDirectory( llvm::StringRef( path.c_str(), path.size() ) );
        clang::DirectoryLookup lookup( entry, sysinclude ? clang::SrcMgr::C_System : clang::SrcMgr::C_User, false );
        headerSearch_.AddSearchPath( lookup, true );
    }

    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::const_iterator iter( ppc.defines().begin() ); iter != ppc.defines().end(); ++iter )
        macroBuilder.defineMacro( iter->first, iter->second );

    // Setup new preprocessor instance.
    preprocessor_.reset
    (
        new clang::Preprocessor
        (
            ppOpts_,
            *diagEng_,
            *langOpts_,
            &*targetInfo_,
            sourceManager_,
            headerSearch_,
            moduleLoader_
        )
    );

    preprocessor().setPredefines( predefinesStream.str() );
    preprocessor().SetSuppressIncludeNotFoundError( true );
}

Headers Preprocessor::scanHeaders( PreprocessingContext const & ppc, llvm::StringRef filename )
{
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
        *diagEng_->getClient(),
        *langOpts_,
        preprocessor()
    );

    Headers result;

    // Do not let #pragma once interfere with cache.
    preprocessor().setPragmasEnabled( false );
    preprocessor().SetMacroExpansionOnlyInDirectives();

    HeaderTracker headerTracker( preprocessor(), cache_ );
    preprocessor().addPPCallbacks( new HeaderScanner( headerTracker, filename,
        preprocessor(), ppc.ignoredHeaders(), result ) );

    preprocessor().EnterMainSourceFile();
    if ( diagEng_->hasFatalErrorOccurred() )
        return result;
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

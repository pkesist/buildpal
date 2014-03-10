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
            bool isAngled,
            clang::CharSourceRange filenameRange,
            clang::FileEntry const * file,
            llvm::StringRef SearchPath,
            llvm::StringRef RelativePath,
            clang::Module const * imported) LLVM_OVERRIDE
        {
            if ( !file )
            {
                std::cerr << "ERROR: Could not find header <" << fileName.str() << ">.\n";
                return;
            }
            headerTracker_.inclusionDirective( SearchPath, RelativePath, isAngled, file );
        }

        virtual void ReplaceFile( clang::FileEntry const * & file ) LLVM_OVERRIDE
        {
            headerTracker_.replaceFile( file );
        }

        virtual void FileChanged( clang::SourceLocation loc, FileChangeReason reason,
            clang::SrcMgr::CharacteristicKind, clang::FileID exitedFID ) LLVM_OVERRIDE
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

        virtual void EndOfMainFile() override
        {
            headers_ = headerTracker_.exitSourceFile();
        }

        virtual void FileSkipped
        (
            clang::FileEntry const & fileEntry,
            clang::Token const &,
            clang::SrcMgr::CharacteristicKind
        ) LLVM_OVERRIDE
        {
            headerTracker_.headerSkipped();
        }

        virtual void MacroExpands( clang::Token const & macroNameTok, clang::MacroDirective const * md, clang::SourceRange, clang::MacroArgs const * ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void MacroDefined( clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroDefined( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void MacroUndefined( clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUndefined( macroNameTok.getIdentifierInfo()->getName(), md );
        }

        virtual void Defined( clang::Token const & macroNameTok, clang::MacroDirective const * md, clang::SourceRange ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void Ifdef(clang::SourceLocation Loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void Ifndef(clang::SourceLocation Loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName(), md ); 
        }

        virtual void PragmaDirective( clang::SourceLocation Loc, clang::PragmaIntroducerKind introducer ) LLVM_OVERRIDE
        {
            clang::Token const token( preprocessor_.LookAhead( 0 ) );
            if ( token.is( clang::tok::identifier ) && token.getIdentifierInfo()->getName() == "once" )
            {
                headerTracker_.pragmaOnce();
            }
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
            int * ) LLVM_OVERRIDE
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
    diagID_    ( new clang::DiagnosticIDs() ),
    diagOpts_  ( new clang::DiagnosticOptions() ),
    diagEng_   ( new clang::DiagnosticsEngine( diagID_, &*diagOpts_ ) ),
    ppOpts_    ( new clang::PreprocessorOptions() ),
    langOpts_  ( new clang::LangOptions() ),
    targetOpts_( createTargetOptions() ),
    targetInfo_( clang::TargetInfo::CreateTargetInfo( *diagEng_, &*targetOpts_) ),
    hsOpts_    ( new clang::HeaderSearchOptions() ),
    cache_     ( cache )
{
    diagEng_->setClient( new DiagnosticConsumer() );
   
    // Configure the include paths.
    hsOpts_->UseBuiltinIncludes = false;
    hsOpts_->UseStandardSystemIncludes = false;
    hsOpts_->UseStandardCXXIncludes = false;
    hsOpts_->Sysroot.clear();
}

std::size_t Preprocessor::setupPreprocessor( PreprocessingContext const & ppc, llvm::StringRef fileName )
{
    // Initialize file manager.
    fileManager_.reset( new clang::FileManager( fsOpts_ ) );
    fileManager().addStatCache( new MemorizeStatCalls_PreventOpenFile() );
    clang::FileEntry const * mainFileEntry = fileManager().getFile( fileName );
    if ( !mainFileEntry )
        throw std::runtime_error( "Could not find source file." );

    // Initialize source manager.
    sourceManager_.reset( new clang::SourceManager( *diagEng_, fileManager(), false ) );
    sourceManager().createMainFileID( mainFileEntry );

    // Setup search path.
    headerSearch_.reset( new clang::HeaderSearch( hsOpts_, sourceManager(), *diagEng_, *langOpts_, &*targetInfo_ ) );
    std::vector<clang::DirectoryLookup> searchPath;
    std::size_t searchPathId( 0 );
    for ( auto const & path : ppc.userSearchPath() )
    {
        clang::DirectoryEntry const * entry = fileManager().getDirectory( path );
        if ( entry )
        {
            llvm::hash_combine( searchPathId, llvm::hash_combine_range( path.begin(), path.end() ) );
            searchPath.push_back( clang::DirectoryLookup( entry, clang::SrcMgr::C_User, false ) );
        }
    }

    for ( auto const & path : ppc.systemSearchPath() )
    {
        clang::DirectoryEntry const * entry = fileManager().getDirectory( path );
        if ( entry );
        {
            llvm::hash_combine( searchPathId, llvm::hash_combine_range( path.begin(), path.end() ) );
            searchPath.push_back( clang::DirectoryLookup( entry, clang::SrcMgr::C_System, false ) );
        }
    }

    headerSearch_->SetSearchPaths( searchPath, 0, ppc.userSearchPath().size(), false );

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
            sourceManager(),
            *headerSearch_,
            moduleLoader_
        )
    );

    preprocessor().setPredefines( predefinesStream.str() );
    preprocessor().SetSuppressIncludeNotFoundError( true );
    return searchPathId;
}

void Preprocessor::scanHeaders( PreprocessingContext const & ppc, llvm::StringRef fileName, Headers & headers )
{
    std::size_t const searchPathId = setupPreprocessor( ppc, fileName );
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

    preprocessor().SetMacroExpansionOnlyInDirectives();

    HeaderTracker headerTracker( preprocessor(), searchPathId, cache_ );
    preprocessor().addPPCallbacks( new HeaderScanner( headerTracker, fileName,
        preprocessor(), ppc.ignoredHeaders(), headers ) );

    preprocessor().EnterMainSourceFile();
    if ( diagEng_->hasFatalErrorOccurred() )
        return;
    while ( true )
    {
        clang::Token token;
        preprocessor().LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    preprocessor().EndSourceFile();
}


//------------------------------------------------------------------------------

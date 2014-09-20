//------------------------------------------------------------------------------
#include "contentCache_.hpp"
#include "headerScanner_.hpp"
#include "headerTracker_.hpp"
#include "utility_.hpp"

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
#include <clang/Lex/LexDiagnostic.h>
#include <clang/Lex/Preprocessor.h>
#include <clang/Lex/PreprocessorOptions.h>
#include <clang/Rewrite/Frontend/Rewriters.h>
#include <llvm/Config/config.h>
#include <llvm/Support/Host.h>
#include <llvm/Support/Path.h>
#include <llvm/Support/MemoryBuffer.h>
#include <llvm/ADT/SmallString.h>

#include <iostream>
#include <windows.h>
#undef ReplaceFile

void normalize( llvm::SmallString<512> & path )
{
    llvm::SmallString<512> result;

    llvm::sys::path::const_iterator const end = llvm::sys::path::end( path.str() );
    for ( llvm::sys::path::const_iterator iter = llvm::sys::path::begin( path.str() ); iter != end; ++iter )
    {
        if ( *iter == "." )
            continue;
        else if ( *iter == ".." )
        {
            assert( !result.empty() );
            llvm::sys::path::remove_filename( result );
        }
        else
        {
            llvm::sys::path::append( result, *iter );
        }
    }
    llvm::sys::path::native( result );
    path.swap( result );
}

namespace
{
    class PreprocessorCallbacks : public clang::PPCallbacks
    {
    public:
        explicit PreprocessorCallbacks
        (
            HeaderTracker & headerTracker,
            llvm::StringRef filename,
            clang::Preprocessor & preprocessor,
            Headers & includedHeaders,
            HeaderList & missingHeaders
        )
            :
            headerTracker_ ( headerTracker   ),
            preprocessor_  ( preprocessor    ),
            headers_       ( includedHeaders ),
            missingHeaders_( missingHeaders  ),
            filename_      ( filename        )
        {
        }

        virtual ~PreprocessorCallbacks() {}

        virtual void InclusionDirective(
            clang::SourceLocation hashLoc,
            clang::Token const & includeTok,
            llvm::StringRef fileName,
            bool isAngled,
            clang::CharSourceRange filenameRange,
            clang::FileEntry const * file,
            llvm::StringRef searchPath,
            llvm::StringRef relativePath,
            clang::Module const * imported) LLVM_OVERRIDE
        {
            if ( !file )
            {
                missingHeaders_.insert( fileName.str() );
                return;
            }

            headerTracker_.inclusionDirective( searchPath, relativePath, fileName, isAngled, file );
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
                headerTracker_.leaveHeader();
            }
        }

        virtual void EndOfMainFile() override
        {
            headerTracker_.exitSourceFile( headers_ );
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
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
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
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
        }

        virtual void Ifdef(clang::SourceLocation loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
            headerTracker_.ifDirective( loc, md != NULL );
        }

        virtual void Ifndef(clang::SourceLocation loc, clang::Token const & macroNameTok, clang::MacroDirective const * md ) LLVM_OVERRIDE
        {
            headerTracker_.macroUsed( macroNameTok.getIdentifierInfo()->getName() ); 
            headerTracker_.ifDirective( loc, md == 0 );
        }

        virtual void PragmaDirective( clang::SourceLocation loc, clang::PragmaIntroducerKind introducer ) LLVM_OVERRIDE
        {
            clang::Token const token( preprocessor_.LookAhead( 0 ) );
            if ( token.is( clang::tok::identifier ) && token.getIdentifierInfo()->getName() == "once" )
            {
                headerTracker_.pragmaOnce();
            }
        }

        virtual void If( clang::SourceLocation loc, clang::SourceRange conditionRange, bool conditionValue ) LLVM_OVERRIDE
        {
            headerTracker_.ifDirective( loc, conditionValue );
        }

        virtual void Elif( clang::SourceLocation loc, clang::SourceRange conditionRange, bool conditionValue, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.elifDirective( loc, conditionValue );
        }

        virtual void Else( clang::SourceLocation loc, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.elseDirective( loc );
        }

        virtual void Endif( clang::SourceLocation loc, clang::SourceLocation ifLoc ) LLVM_OVERRIDE
        {
            headerTracker_.endifDirective( loc );
        }

    private:
        HeaderTracker & headerTracker_;
        clang::Preprocessor & preprocessor_;
        llvm::StringRef filename_;
        Headers & headers_;
        HeaderList & missingHeaders_;
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
    diagEng_->setEnableAllWarnings( true );
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

    // Initialize source manager.
    sourceManager_.reset( new clang::SourceManager( *diagEng_, fileManager(), false ) );

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
        if ( entry )
        {
            llvm::hash_combine( searchPathId, llvm::hash_combine_range( path.begin(), path.end() ) );
            searchPath.push_back( clang::DirectoryLookup( entry, clang::SrcMgr::C_System, false ) );
        }
    }

    headerSearch_->SetSearchPaths( searchPath, 0, ppc.userSearchPath().size(), false );

    // Create main file.
    clang::FileEntry const * mainFileEntry = fileManager().getFile( fileName );
    if ( !mainFileEntry )
    {
        std::string error( "Could not find source file '" );
        error.append( fileName.str() );
        error.append( "'." );
        throw std::runtime_error( error );
    }

    assert( !sourceManager().isFileOverridden( mainFileEntry ) );
    sourceManager().overrideFileContents( mainFileEntry,
        prepareSourceFile( fileManager(), *mainFileEntry ) );
    sourceManager().createMainFileID( mainFileEntry );

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

    std::string predefines;
    llvm::raw_string_ostream predefinesStream( predefines );
    clang::MacroBuilder macroBuilder( predefinesStream );
    for ( PreprocessingContext::Defines::value_type const & macro : ppc.defines() )
        macroBuilder.defineMacro( macro.first, macro.second );
    for ( PreprocessingContext::Includes::value_type const & include : ppc.forcedIncludes() )
        macroBuilder.append( llvm::Twine( "#include \"" ) + include + "\"" );
    preprocessor().setPredefines( predefinesStream.str() );
    preprocessor().SetSuppressIncludeNotFoundError( true );
    preprocessor().SetMacroExpansionOnlyInDirectives();
    return searchPathId;
}

namespace
{
    struct DiagnosticConsumer : clang::DiagnosticConsumer
    {
        HeaderTracker & headerTracker_;

        explicit DiagnosticConsumer( HeaderTracker & headerTracker )
            : headerTracker_( headerTracker )
        {
        }

        virtual void HandleDiagnostic(
            clang::DiagnosticsEngine::Level level,
            clang::Diagnostic const & info) 
        {
            if ( info.getID() == clang::diag::warn_pp_undef_identifier )
            {
                // We need to get notifications for identifiers which did not get expanded
                // in order to create consistent cache key paths.
                clang::IdentifierInfo const * identifier( info.getArgIdentifier( 0 ) );
                if ( identifier )
                    headerTracker_.macroUsed( identifier->getName() );
            }
        }
    };
}


bool Preprocessor::scanHeaders( PreprocessingContext const & ppc, llvm::StringRef fileName, Headers & headers, HeaderList & missingHeaders )
{
    std::size_t const searchPathId = setupPreprocessor( ppc, fileName );
    HeaderTracker headerTracker( preprocessor(), searchPathId, cache_ );
    diagEng_->setClient( new DiagnosticConsumer( headerTracker ) );
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

    preprocessor().addPPCallbacks( new PreprocessorCallbacks( headerTracker, fileName,
        preprocessor(), headers, missingHeaders ) );
    
    preprocessor().EnterMainSourceFile();
    if ( diagEng_->hasFatalErrorOccurred() )
        return false;
    while ( true )
    {
        clang::Token token;
        preprocessor().LexNonComment( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    preprocessor().EndSourceFile();
    return true;
}


//------------------------------------------------------------------------------

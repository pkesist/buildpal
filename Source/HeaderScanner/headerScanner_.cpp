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
            PreprocessingContext::HeaderRefs & headers )
            :
            sourceManager_( sourceManager ),
            headers_      ( headers       ),
            first_        ( true          )
        {
        }

        virtual ~FileChangeCallback() {}

        virtual void FileChanged(clang::SourceLocation Loc, FileChangeReason Reason,
            clang::SrcMgr::CharacteristicKind FileType, clang::FileID PrevFID = clang::FileID())
        {
            if ( Reason != EnterFile )
                return;
            clang::FileID const fileId( sourceManager_.getFileID( Loc ) );
            clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
            if ( fileEntry )
            {
                if ( first_ )
                {
                    first_ = false;
                    return;
                }
                headers_.insert( std::make_pair( lastRelativePath_, fileEntry->getName() ) );
            }
        }


        virtual void InclusionDirective(clang::SourceLocation HashLoc,
                                        const clang::Token &IncludeTok,
                                        clang::StringRef FileName,
                                        bool IsAngled,
                                        clang::CharSourceRange FilenameRange,
                                        const clang::FileEntry *File,
                                        clang::StringRef SearchPath,
                                        clang::StringRef RelativePath,
                                        const clang::Module *Imported)
        {
            lastRelativePath_ = RelativePath;
        }

    private:
        clang::SourceManager const & sourceManager_;
        PreprocessingContext::HeaderRefs & headers_;
        clang::StringRef lastRelativePath_;
        bool first_;
    };
}  // anonymous namespace

PreprocessingContext::PreprocessingContext( std::string const & filename )
{
    // Create diagnostics.
    compiler_.createDiagnostics();

    clang::PreprocessorOptions & preprocessorOptions( compiler_.getInvocation().getPreprocessorOpts() );

    // Do not use Clang predefines.
    preprocessorOptions.UsePredefines = false;

    // Create target info.
    clang::TargetOptions target_options;
    target_options.Triple = llvm::sys::getDefaultTargetTriple();
    compiler_.setTarget(clang::TargetInfo::CreateTargetInfo(
        compiler_.getDiagnostics(), &target_options));

    clang::CompilerInvocation::setLangDefaults(
        compiler_.getLangOpts(), clang::IK_CXX);

    // Configure the include paths.
    clang::HeaderSearchOptions &hsopts = compiler_.getHeaderSearchOpts();
    hsopts.UseBuiltinIncludes = false;
    hsopts.UseStandardSystemIncludes = false;
    hsopts.UseStandardCXXIncludes = false;

    // Create the rest.
    compiler_.createFileManager();
    compiler_.createSourceManager( compiler_.getFileManager() );

    clang::FileEntry const * mainFileEntry = compiler_.getFileManager().getFile( filename );
    compiler_.getSourceManager().createMainFileID( mainFileEntry );
}

void PreprocessingContext::addIncludePath( std::string const & path, bool sysinclude )
{
    searchPath_.push_back( std::make_pair( path, sysinclude ) );
}

void PreprocessingContext::addMacro( std::string const & name, std::string const & value )
{
    defines_.push_back( std::make_pair( name, value ) );
}

PreprocessingContext::HeaderRefs PreprocessingContext::scanHeaders()
{
    // Setup new preprocessor instance.
    compiler_.createPreprocessor();
    clang::Preprocessor & preprocessor = compiler_.getPreprocessor();
    clang::HeaderSearch & headers = preprocessor.getHeaderSearchInfo();
    // Setup search path.
    for ( std::vector<std::pair<std::string, bool> >::const_iterator iter( searchPath_.begin() ); iter != searchPath_.end(); ++iter )
    {
        std::string const & path = iter->first;
        bool const sysinclude = iter->second;
        clang::DirectoryEntry const * entry = compiler_.getFileManager().getDirectory( llvm::StringRef( path.c_str(), path.size() ) );
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
    for ( std::vector<std::pair<std::string, std::string> >::const_iterator iter( defines_.begin() ); iter != defines_.end(); ++iter )
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
    } const diagnosticsGuard( *compiler_.getDiagnostics().getClient(), compiler_.getLangOpts(), preprocessor );

    HeaderRefs result;
    preprocessor.addPPCallbacks( new FileChangeCallback( compiler_.getSourceManager(), result ) );

    preprocessor.EnterMainSourceFile();
    while ( true )
    {
        clang::Token token;
        preprocessor.Lex( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    return result;
}

int main(void)
{
    PreprocessingContext pc( "D:\\Sandboxes\\PKE\\Libraries\\Boost\\boost_1_53_0\\boost\\phoenix.hpp" );
    pc.addIncludePath( "D:\\Sandboxes\\PKE\\Libraries\\Boost\\boost_1_53_0", false );
    pc.scanHeaders();
}


//------------------------------------------------------------------------------

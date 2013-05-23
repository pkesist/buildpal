//------------------------------------------------------------------------------
#include "headerScanner_.hpp"

#include "clang/Basic/Diagnostic.h"
#include "clang/Basic/DiagnosticOptions.h"
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
        explicit FileChangeCallback( clang::SourceManager const & sourceManager, std::set<std::string> & headers )
            :
            sourceManager_( sourceManager ),
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
            clang::FileEntry const * const fileEntry( sourceManager_.getFileEntryForID( fileId ) );
            if ( fileEntry )
            {
                char const * name( fileEntry->getName() );
                headers_.insert( name );
            }
        }

        clang::SourceManager const & sourceManager_;
        std::set<std::string> & headers_;
    };
}  // anonymous namespace

PreprocessingContext::PreprocessingContext( std::string const & filename )
{
    // Create diagnostics.
    m_compiler.createDiagnostics();

    // Create target info.
    // XXX make this configurable?
    clang::TargetOptions target_options;
    target_options.Triple = llvm::sys::getDefaultTargetTriple();
    m_compiler.setTarget(clang::TargetInfo::CreateTargetInfo(
        m_compiler.getDiagnostics(), &target_options));

    clang::CompilerInvocation::setLangDefaults(
        m_compiler.getLangOpts(), clang::IK_CXX);

    // Configure the include paths.
    clang::HeaderSearchOptions &hsopts = m_compiler.getHeaderSearchOpts();
    hsopts.UseBuiltinIncludes = false;
    hsopts.UseStandardSystemIncludes = false;
    hsopts.UseStandardCXXIncludes = false;

    // Create the rest.
    m_compiler.createFileManager();
    m_compiler.createSourceManager(m_compiler.getFileManager());

    clang::FileEntry const * mainFileEntry = m_compiler.getFileManager().getFile( filename );
    m_compiler.getSourceManager().createMainFileID( mainFileEntry );

    m_compiler.createPreprocessor();
}

void PreprocessingContext::addIncludePath( std::string const & path, bool sysinclude )
{
    clang::Preprocessor & preprocessor = m_compiler.getPreprocessor();
    clang::HeaderSearch & headers = m_compiler.getPreprocessor().getHeaderSearchInfo();
        
    clang::FileManager & filemgr = headers.getFileMgr();
    const clang::DirectoryEntry *entry =
        filemgr.getDirectory(llvm::StringRef(path.c_str(), path.size()));

    // Take a copy of the existing search paths, and add the new one. If
    // it's a system path, insert it in after "system_dir_end". If it's a
    // user path, simply add it to the end of the vector.
    std::vector<clang::DirectoryLookup> search_paths(
        headers.search_dir_begin(), headers.search_dir_end());
    // TODO make sure it's not already in the list.
    const unsigned int n_quoted = std::distance(
        headers.quoted_dir_begin(), headers.quoted_dir_end());
    const unsigned int n_angled = std::distance(
        headers.angled_dir_begin(), headers.angled_dir_end());
    if (sysinclude)
    {
        clang::DirectoryLookup lookup(
            entry, clang::SrcMgr::C_System, false);
        search_paths.insert(
            search_paths.begin() + (n_quoted + n_angled), lookup);
    }
    else
    {
        clang::DirectoryLookup lookup(
            entry, clang::SrcMgr::C_User, false);
        search_paths.push_back(lookup);
    }
    headers.SetSearchPaths( search_paths, n_quoted, n_quoted + n_angled, false);
}

std::set<std::string> PreprocessingContext::scanHeaders()
{
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
    } const diagnosticsGuard( *m_compiler.getDiagnostics().getClient(), m_compiler.getLangOpts(), m_compiler.getPreprocessor() );

    std::set<std::string> headers;
    clang::Preprocessor & preprocessor( m_compiler.getPreprocessor() );
    preprocessor.addPPCallbacks( new FileChangeCallback( m_compiler.getSourceManager(), headers ) );

    preprocessor.EnterMainSourceFile();
    while ( true )
    {
        clang::Token token;
        preprocessor.Lex( token );
        if ( token.is( clang::tok::eof ) )
            break;
    }
    return headers;
}

int main(void)
{
    PreprocessingContext pc( "D:\\Sandboxes\\PKE\\Libraries\\Boost\\boost_1_53_0\\boost\\phoenix.hpp" );
    pc.addIncludePath( "D:\\Sandboxes\\PKE\\Libraries\\Boost\\boost_1_53_0", false );
    pc.scanHeaders();
}


//------------------------------------------------------------------------------

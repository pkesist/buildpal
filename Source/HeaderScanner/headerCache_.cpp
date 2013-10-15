//------------------------------------------------------------------------------
#include "headerCache_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/make_shared.hpp>

#include <iostream>
//------------------------------------------------------------------------------

clang::FileEntry const * CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );

    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, memoryBuffer_.get(), true );
    return result;
}

void CacheEntry::generateContent()
{
    if ( memoryBuffer_ )
        return;

    struct GenerateContent
    {
        typedef void result_type;

        GenerateContent( llvm::raw_string_ostream & ostream )
            : ostream_( ostream ) {}

        void operator()( MacroWithUsage const & mwu )
        {
            if ( mwu.first == MacroUsage::defined )
            {
                Macro const & macro( mwu.second );
                ostream_ << "#define " << macroValue( macro ) << '\n';
            }

            if ( mwu.first == MacroUsage::undefined )
            {
                Macro const & macro( mwu.second );
                ostream_ << "#undef " << macroName( macro ) << '\n';
            }
        }

        void operator()( CacheEntryPtr const & ce )
        {
            if ( !ce->memoryBuffer_ )
                ce->generateContent();
            ostream_ << ce->buffer_;
        }

        llvm::raw_string_ostream & ostream_;
    };
    
    llvm::raw_string_ostream defineStream( buffer_ );
    GenerateContent contentGenerator( defineStream );
    std::for_each( headerContent().begin(), headerContent().end(),
        [&]( HeaderEntry const & he ) { boost::apply_visitor( contentGenerator, he ); } );
    defineStream << '\0';
    defineStream.flush();
    memoryBuffer_.reset( llvm::MemoryBuffer::getMemBuffer( buffer_, "", true ) );
}

std::string Cache::uniqueFileName()
{
    std::stringstream result;
    result << "__cached_file_" << ++counter_;
    return result.str();
}


void CacheEntry::releaseFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );
    assert( result );
    sourceManager.disableFileContentsOverride( result );
}

CacheEntryPtr Cache::findEntry( llvm::StringRef fileName, MacroState const & macroState )
{
    HeadersInfo::iterator const iter( headersInfo().find( fileName ) );
    if ( iter == headersInfo().end() )
        return CacheEntryPtr();
    CacheEntryPtr result( iter->second->findCacheEntry( macroState ) );
    if ( result )
    {
        ++hits_;
        headersInfoList_.splice( headersInfoList_.begin(), headersInfoList_, iter->second );
        result->generateContent();
    }
    else
    {
        ++misses_;
    }
    return result;
}


CacheEntryPtr Cache::HeaderInfo::findCacheEntry( MacroState const & macroState )
{
    for
    (
        CacheList::iterator headerInfoIter( cacheList_.begin() );
        headerInfoIter != cacheList_.end();
        ++headerInfoIter
    )
    {
        if (
            std::find_if
            (
                (*headerInfoIter)->usedMacros().begin(),
                (*headerInfoIter)->usedMacros().end(),
                [&]( Macro const & macro )
                {
                    MacroState::const_iterator const iter( macroState.find( macroName( macro ) ) );
                    if ( iter == macroState.end() )
                        return !macroValue( macro ).empty();
                    return iter->getValue() != macroValue( macro );
                }
            ) == (*headerInfoIter)->usedMacros().end()
        )
        {
            cacheList_.splice( cacheList_.begin(), cacheList_, headerInfoIter );
            return *headerInfoIter;
        }
    }
    return CacheEntryPtr();
}


//------------------------------------------------------------------------------

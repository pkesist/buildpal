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
        sourceManager.overrideFileContents( result, buffer_.get(), true );
    return result;
}

void CacheEntry::generateContent()
{
    if ( buffer_.get() )
        return;

    // Cache the result.
    std::string content;
    llvm::raw_string_ostream defineStream( content );
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
                assert( macro.second.data() );
                ostream_ << "#define " << macro.second << '\n';
            }

            if ( mwu.first == MacroUsage::undefined )
            {
                Macro const & macro( mwu.second );
                assert( macro.second.data() );
                ostream_ << "#undef " << macro.first << '\n';
            }
        }

        void operator()( CacheEntryPtr const & ce )
        {
            if ( !ce->buffer_ )
                ce->generateContent();
            ostream_ << ce->buffer_->getBuffer();
        }

        llvm::raw_string_ostream & ostream_;
    } contentGenerator( defineStream );

    std::for_each( headerContent().begin(), headerContent().end(),
        [&]( HeaderEntry const & he ) { boost::apply_visitor( contentGenerator, he ); } );

    defineStream << '\0';
    buffer_.reset( llvm::MemoryBuffer::getMemBufferCopy( defineStream.str(), "" ) );
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
    boost::unique_lock<boost::recursive_mutex> lock( mutex_ );
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
                    MacroState::const_iterator const iter( macroState.find( macro.first ) );
                    if ( iter == macroState.end() )
                        return !macro.second.empty();
                    return iter->getValue() != macro.second;
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

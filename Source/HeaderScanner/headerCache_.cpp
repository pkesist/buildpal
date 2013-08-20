//------------------------------------------------------------------------------
#include "headerCache_.hpp"

#include "utility_.hpp"

#include <clang/Lex/Preprocessor.h>

#include <boost/make_shared.hpp>

#include <iostream>
//------------------------------------------------------------------------------

clang::FileEntry const * Cache::CacheEntry::getFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );

    if ( !sourceManager.isFileOverridden( result ) )
        sourceManager.overrideFileContents( result, buffer_.get(), true );
    return result;
}

void Cache::CacheEntry::generateContent()
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

        void operator()( boost::shared_ptr<CacheEntry> const & ce )
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


void Cache::CacheEntry::releaseFileEntry( clang::SourceManager & sourceManager )
{
    clang::FileEntry const * result( sourceManager.getFileManager().getVirtualFile( fileName_, fileName_.size(), 0 ) );
    assert( result );
    sourceManager.disableFileContentsOverride( result );
}

boost::shared_ptr<Cache::CacheEntry> Cache::findEntry( llvm::StringRef fileName, clang::Preprocessor const & preprocessor )
{
    boost::unique_lock<boost::recursive_mutex> lock( mutex_ );
    HeadersInfo::iterator const iter( headersInfo().find( fileName ) );
    if ( iter == headersInfo().end() )
        return boost::shared_ptr<Cache::CacheEntry>();
    boost::shared_ptr<Cache::CacheEntry> result( iter->second->find( preprocessor ) );
    if ( result )
    {
        headersInfoList_.splice( headersInfoList_.begin(), headersInfoList_, iter->second );
        result->generateContent();
    }
    return result;
}

boost::shared_ptr<Cache::CacheEntry> Cache::HeaderInfo::find( clang::Preprocessor const & preprocessor )
{
    for
    (
        CacheList::iterator headerInfoIter( cacheList_.begin() );
        headerInfoIter != cacheList_.end();
        ++headerInfoIter
    )
    {
        Macros const & inputMacros( (*headerInfoIter)->usedMacros() );
        bool isMatch( true );

        struct MacroIsNotCurrent
        {
            clang::Preprocessor const & pp_;
            
            explicit MacroIsNotCurrent( clang::Preprocessor const & pp ) : pp_( pp ) {}

            bool operator()( Macro const & macro )
            {
                return macro.second != macroDefFromSourceLocation( pp_,
                    pp_.getMacroDirective( pp_.getIdentifierInfo( macro.first ) ) );
            }
        } macroIsNotCurrent( preprocessor );
        
        if
        (
            std::find_if
            (
                inputMacros.begin(), inputMacros.end(),
                macroIsNotCurrent
            ) != inputMacros.end()
        )
            continue;

        cacheList_.splice( cacheList_.begin(), cacheList_, headerInfoIter );
        return *headerInfoIter;
    }
    return boost::shared_ptr<Cache::CacheEntry>();
}

boost::shared_ptr<Cache::CacheEntry> Cache::HeaderInfo::insert( BOOST_RV_REF(CacheEntry) value )
{
    boost::shared_ptr<Cache::CacheEntry> const result
    (
        boost::make_shared<CacheEntry>
        (
        #if defined(BOOST_NO_CXX11_RVALUE_REFERENCES)
            boost::ref( value )
        #else
            boost::move( value )
        #endif
        )
    );

    cacheList_.push_front( result );
    return result;
}


//------------------------------------------------------------------------------

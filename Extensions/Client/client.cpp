#include "client.hpp"

#include <boost/asio.hpp>
#include <boost/system/error_code.hpp>

#include <llvm/ADT/SmallVector.h>
#include <llvm/Support/CommandLine.h>
#include <llvm/Support/Process.h>

#include <array>
#include <ctime>
#include <codecvt>
#include <deque>
#include <iostream>
#include <fstream>
#include <sstream>
#include <list>
#include <memory>
#include <string>

#include <shellapi.h>
#include <shlwapi.h>
#include <windows.h>

#ifdef __GNUC__
#define alloca __builtin_alloca
#endif

namespace
{
    class StringSaver : public llvm::cl::StringSaver
    {
    public:
        virtual const char * SaveString( char const * str )
        {
            storage_.push_back( str );
            return storage_.back().c_str();
        }

    private:
        std::deque<std::string> storage_;
    };

    template<typename T>
    void to_byte_array( T val, std::array<unsigned char, sizeof(T)> & result )
    {
        for ( unsigned int x(0); x < sizeof(T); ++x )
        {
            unsigned int const index = sizeof(T) - x - 1;
            result[x] = static_cast<unsigned char>(((val) >> (index * 8)) & 0xFF);
        }
    }

    template<typename T>
    std::array<unsigned char, sizeof(T)> to_byte_array( T val )
    {
        std::array<unsigned char, sizeof(T)> result;
        to_byte_array( val, result );
        return result;
    }

    template <unsigned int len>
    struct UnsignedType {};

    template <> struct UnsignedType<2> { typedef std::uint16_t type; };
    template <> struct UnsignedType<4> { typedef std::uint32_t type; };
    template <> struct UnsignedType<8> { typedef std::uint64_t type; };

    template <unsigned int len>
    typename UnsignedType<len>::type from_byte_array( unsigned char const * value )
    {
        typename UnsignedType<len>::type result = value[0];
        for ( unsigned x = 1; x < len; ++x )
        {
            result <<= 8;
            result += value[x];
        }
        return result;
    }

    class MsgSender
    {
    public:
        MsgSender() { initMessage(); }

        void addPart( char const * ptr )
        {
            addPart( ptr, strlen( ptr ) );
        }

        void addPart( char const * ptr, uint32_t size )
        {
            std::array<unsigned char, 4> const ar = to_byte_array(size);
            lengths_.push_back( ar );
            buffers_.push_back( boost::asio::buffer( lengths_.back().data(), lengths_.back().size() ) );
            if ( size != 0 )
                buffers_.push_back( boost::asio::buffer( ptr, size ) );
            totalLength_ += lengths_.back().size() + size;
            partCount_ += 1;
        }

        template <class Stream>
        void send( Stream & sock, boost::system::error_code & error )
        {
            to_byte_array( totalLength_, totalLengthBuffer_ );
            to_byte_array( partCount_  , partCountBuffer_ );
            boost::asio::write( sock, buffers_, error );
            initMessage();
        }

    private:
        void initMessage()
        {
            buffers_.clear();
            lengths_.clear();
            partCount_ = 0;
            buffers_.push_back( boost::asio::buffer( totalLengthBuffer_.data(), totalLengthBuffer_.size() ) );
            buffers_.push_back( boost::asio::buffer( partCountBuffer_.data(), partCountBuffer_.size() ) );
            totalLength_ = partCountBuffer_.size();
        }

    private:
        uint32_t totalLength_;
        uint16_t partCount_;
        std::array<unsigned char, 4> totalLengthBuffer_;
        std::array<unsigned char, 2> partCountBuffer_;
        std::deque<std::array<unsigned char, 4> > lengths_;
        std::vector<boost::asio::const_buffer> buffers_;
    };


    class MsgReceiver
    {
    public:
        template <class Stream>
        void getMessage( Stream & sock, boost::system::error_code & error )
        {
            parts_.clear();

            std::array<unsigned char, 6> lengthBuffer;
            boost::system::error_code readError;
            boost::asio::read( sock, boost::asio::buffer( lengthBuffer.data(), lengthBuffer.size() ), error );
            if ( error )
                return;
            std::uint32_t const totalSize = from_byte_array<4>( &lengthBuffer[0] ) - 2;
            std::uint16_t const partCount = from_byte_array<2>( &lengthBuffer[4] );

            buf_.resize( totalSize );
            boost::asio::read( sock, boost::asio::buffer( &buf_[0], totalSize ), error );
            if ( error )
                return;

            char const * const start = buf_.data();
            unsigned char const * const ustart = reinterpret_cast<unsigned char const *>( start );
            std::size_t offset( 0 );
            std::size_t partsFound = 0;
            while ( offset < totalSize )
            {
                std::uint32_t const partLen = from_byte_array<4>( ustart + offset );
                offset += 4;
                parts_.push_back( llvm::StringRef( start + offset, partLen ) );
                offset += partLen;
                ++partsFound;
            }
            if ( ( offset != totalSize ) || ( partsFound != partCount ) )
            {
                error = boost::system::errc::make_error_code( boost::system::errc::protocol_error );
                return;
            }
        }

        llvm::StringRef getPart( std::size_t index )
        {
            if ( index >= parts_.size() )
                return llvm::StringRef();
            return parts_[ index ];
        }

        std::size_t parts() const { return parts_.size(); }

    private:
        std::vector<char> buf_;
        std::vector<llvm::StringRef> parts_;
    };

    std::unique_ptr<char []> getPipeData( HANDLE pipe, DWORD & size )
    {
        DWORD available = 0;
        if ( !PeekNamedPipe( pipe, 0, 0, 0, &available, 0 ) )
            available = 0;

        std::unique_ptr<char []> buffer( new char[ available + 1 ] );
        if ( available )
            ReadFile( pipe, buffer.get(), available, &size, NULL );
        else
            size = 0;
        buffer[ available ] = '\0';
        return buffer;
    }

    class Fallback
    {
    public:
        explicit Fallback( FallbackFunction const fallbackFunction, void * fallbackParam )
            : fallbackFunction_( fallbackFunction ),
              fallbackParam_( fallbackParam )
        {}

        int complete( std::string const & error ) const
        {
            return fallbackFunction_
                ? fallbackFunction_( error.c_str(), fallbackParam_ )
                : -1
            ;
        }

    private:
        FallbackFunction fallbackFunction_;
        void * fallbackParam_;
    };
}

Environment::Environment( void * vpEnv, bool unicode )
{
    if ( !vpEnv )
    {
        unicode = false;
        vpEnv = GetEnvironmentStringsA();
    }

    if ( unicode )
    {
        wchar_t const * start = static_cast<wchar_t const *>( vpEnv );
        while ( *start )
        {
            wchar_t const * equalPos( 0 );
            wchar_t const * iter = start;
            for ( ; *iter; ++iter )
            {
                if ( ( *iter == '=' ) && !equalPos )
                    equalPos = iter;
            }
            // Ignore cmd.exe bookkeeping variables (=::, =C:, =ExitCode)
            if ( equalPos != start )
            {
                std::wstring const key( start, equalPos - start );
                std::wstring const value( equalPos + 1, iter );
                std::wstring_convert<std::codecvt_utf8<wchar_t>, wchar_t> convert;
                envMap_.insert( std::make_pair(
                    convert.to_bytes( key ),
                    convert.to_bytes( value ) ) );
            }
            start = iter + 1;
        }
    }
    else
    {
        char const * start = static_cast<char const *>( vpEnv );
        while ( *start )
        {
            char const * equalPos( 0 );
            char const * iter = start;
            for ( ; *iter; ++iter )
            {
                if ( ( *iter == '=' ) && !equalPos )
                    equalPos = iter;
            }
            if ( equalPos != start )
            {
                std::string const key( start, equalPos - start );
                std::string const value( equalPos + 1, iter );
                envMap_.insert( std::make_pair( key, value ) );
            }
            start = iter + 1;
        }
    }
}

llvm::Optional<std::string> Environment::get( llvm::StringRef str ) const
{
    EnvMap::const_iterator const iter = envMap_.find( str );
    if ( iter != envMap_.end() )
        return iter->second;
    return llvm::sys::Process::GetEnv( str );
}

void Environment::remove( llvm::StringRef str )
{
    envMap_.erase( str );
}

void Environment::add( llvm::StringRef key, llvm::StringRef val )
{
    envMap_.insert( std::pair<std::string, std::string>( key, val ) ); 
}

char * Environment::createEnvBlock() const
{
    if ( envMap_.empty() )
        return 0;

    std::string result;
    for ( EnvMap::const_iterator iter = envMap_.begin(); iter != envMap_.end(); ++iter )
    {
        result.append( iter->first );
        result.push_back( '=' );
        result.append( iter->second );
        result.push_back( '\0' );
    }
    envBlock_.swap( result );
    return const_cast<char *>( envBlock_.c_str() );
}

void getPath( Environment const & env, PathList & result )
{
    llvm::Optional<std::string> path = env.get( "PATH" );
    if ( !path )
        return;
    std::size_t last = 0;
    for ( std::size_t iter( 0 ); iter != path->size(); ++iter )
    {
        if ( ( (*path)[ iter ] == ';' ) && ( iter != last + 1 ) )
        {
            result.push_back( std::string( path->c_str() + last, path->c_str() + iter ) );
            last = iter + 1;
        }
    }
}

int createProcess( wchar_t const * appName, wchar_t * commandLine, Environment const * env, wchar_t const * currentDirectory )
{
    STARTUPINFOW startupInfo = { sizeof(startupInfo) };
    PROCESS_INFORMATION processInfo;

    BOOL const apiResult = CreateProcessW(
        appName,
        commandLine,
        NULL,
        NULL,
        FALSE,
        0,
        env ? env->createEnvBlock() : 0,
        currentDirectory,
        &startupInfo,
        &processInfo
    );

    if ( apiResult )
    {
        ::WaitForSingleObject( processInfo.hProcess, INFINITE );
        int result;
        GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
        CloseHandle( processInfo.hProcess );
        CloseHandle( processInfo.hThread );
        return result;
    }
    else
    {
        return -1;
    }
}

int createProcess( char const * appName, char * commandLine, Environment const * env, char const * currentDirectory )
{
    STARTUPINFO startupInfo = { sizeof(startupInfo) };
    PROCESS_INFORMATION processInfo;

    BOOL const apiResult = CreateProcessA(
        appName,
        commandLine,
        NULL,
        NULL,
        FALSE,
        0,
        env ? env->createEnvBlock() : 0,
        currentDirectory,
        &startupInfo,
        &processInfo
    );

    if ( apiResult )
    {
        ::WaitForSingleObject( processInfo.hProcess, INFINITE );
        int result;
        GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
        CloseHandle( processInfo.hProcess );
        CloseHandle( processInfo.hThread );
        return result;
    }
    else
    {
        return -1;
    }
}

bool findOnPath( PathList const & pathList, std::string const & file, std::string & result )
{
    for ( PathList::const_iterator iter( pathList.begin() ); iter != pathList.end(); ++iter )
    {
        char tmp[ MAX_PATH ];
        PathCombine( tmp, iter->c_str(), file.c_str() );
        if ( PathFileExists( tmp ) )
        {
            result = tmp;
            return true;
        }
    }
    return false;
}

int distributedCompile(
    char const * compilerToolset,
    char const * compilerExecutable,
    Environment & env,
    char const * commandLine,
    char const * currentPath,
    char const * portName,
    FallbackFunction fallbackFunc,
    void * fallbackParam,
    HANDLE stdOutHandle,
    HANDLE stdErrHandle
)
{
    if ( !stdOutHandle )
        stdOutHandle = GetStdHandle( STD_OUTPUT_HANDLE );
    if ( !stdErrHandle )
        stdErrHandle = GetStdHandle( STD_ERROR_HANDLE );

    Fallback const fallback( fallbackFunc, fallbackParam );
    env.remove( "VS_UNICODE_OUTPUT" );

#ifdef BOOST_WINDOWS
    HANDLE pipe;
    char const pipeStreamPrefix[] = "\\\\.\\pipe\\BuildPal_";
    std::size_t const pipeStreamPrefixSize = sizeof(pipeStreamPrefix) / sizeof(pipeStreamPrefix[0]) - 1;

    std::string pipeName( pipeStreamPrefix );
    pipeName.append( portName );
    for ( ; ;  )
    {
        pipe = ::CreateFile(
            pipeName.c_str(),                             // LPCTSTR lpFileName,
            GENERIC_READ | GENERIC_WRITE,                 // DWORD dwDesiredAccess,
            0,                                            // DWORD dwShareMode,
            NULL,                                         // LPSECURITY_ATTRIBUTES lpSecurityAttributes,
            OPEN_EXISTING,                                // DWORD dwCreationDisposition,
            FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED, // DWORD dwFlagsAndAttributes,
            NULL                                          // HANDLE hTemplateFile
        );

        if ( pipe != INVALID_HANDLE_VALUE )
            break;

        if ( GetLastError() == ERROR_PIPE_BUSY )
        {
            WaitNamedPipe( pipeName.c_str(), NMPWAIT_USE_DEFAULT_WAIT );
            continue;
        }
            
        boost::system::error_code const error( ::GetLastError(), boost::system::system_category() );
        std::stringstream stream;
        stream << "Failed to create pipe '" << pipeName << "'. (" << error.message() << ").";
        return fallback.complete( stream.str() );
    }
    typedef boost::asio::windows::stream_handle StreamType;

    boost::asio::io_service ioService;
    StreamType sock( ioService, pipe );
#else
    unsigned long const lport = std::strtoul( portName.data() );
    if ( lport > std::numeric_limits<unsigned short>::max() )
        return fallback.complete( "Failed to parse BP_MANAGER_PORT environment variable value." );
    unsigned short const port = static_cast<unsigned short>( lport );
    
    boost::asio::ip::address localhost;
    boost::system::error_code addressError;
    localhost = boost::asio::ip::address::from_string( "127.0.0.1", addressError );
    if ( addressError )
    {
        std::stringstream stream;
        stream << "Could not resolve address. (" << addressError.message() << ").";
        return fallback.complete( stream.str() );
    }
    
    boost::asio::io_service ioService;
    typedef boost::asio::ip::tcp::socket StreamType;
    boost::asio::ip::tcp::socket sock( ioService );
    boost::asio::ip::tcp::endpoint endpoint;
    endpoint.address( localhost );
    endpoint.port( port );
    
    boost::system::error_code connectError;
    sock.connect( endpoint, connectError );
    if ( connectError )
    {
        std::stringstream stream;
        stream << "Failed to connect to 'localhost:" << port << "'.";
        return fallback.complete( stream.str() );
    }
#endif

    MsgSender msgSender;

    msgSender.addPart( compilerToolset );
    msgSender.addPart( compilerExecutable );

    llvm::Optional<std::string> const include = env.get( "INCLUDE" );
    if ( include )
        msgSender.addPart( include->c_str(), include->size() );
    else
        msgSender.addPart( "" );

    if ( currentPath )
    {
        msgSender.addPart( currentPath );
    }
    else
    {
        DWORD const currentPathSize( GetCurrentDirectory( 0, NULL ) );
        char * tmpCurrentPath = static_cast<char *>( alloca( currentPathSize ) );
        GetCurrentDirectory( currentPathSize, tmpCurrentPath );
        msgSender.addPart( tmpCurrentPath );
    }

    StringSaver saver;
    typedef llvm::SmallVector<char const *, 32> ArgVector;
    ArgVector argv;
    llvm::cl::TokenizeWindowsCommandLine( commandLine, saver, argv );

    llvm::Optional<std::string> clEnvOpts = env.get( "CL" );
    if ( clEnvOpts )
    {
        ArgVector envArgv;
        llvm::cl::TokenizeWindowsCommandLine( *clEnvOpts, saver, envArgv );
        // Environment arguments considered to be before than the real ones.
        argv.insert( argv.begin() + 1, envArgv.begin(), envArgv.end() );
    }

    if ( !llvm::cl::ExpandResponseFiles( saver, llvm::cl::TokenizeWindowsCommandLine, argv ) )
    {
        // ExpandResponseFiles always returns false, even on success.
        // Fixed in trunk, but did not make it to Clang 3.4.
        //return fallback.complete( "Failed to expand response files." );
    }

    for ( ArgVector::const_iterator iter( argv.begin() ); iter != argv.end(); ++iter )
        msgSender.addPart( *iter );

    boost::system::error_code writeError;
    msgSender.send( sock, writeError );
    if ( writeError )
    {
        std::stringstream stream;
        stream << "Failed to send message (" << writeError.message() << ").";
        return fallback.complete( stream.str() );
    }

    MsgReceiver receiver;
    while ( true )
    {
        boost::system::error_code error;
        receiver.getMessage( sock, error );
        if ( error )
        {
            std::stringstream stream;
            stream << "Failed to get message (" << error.message() << ").";
            return fallback.complete( stream.str() );
        }

        if ( receiver.parts() == 0 )
            return fallback.complete( "Empty message." );

        llvm::StringRef const request = receiver.getPart( 0 );

        if ( request == "RUN_LOCALLY" )
        {
            return createProcess( compilerExecutable, const_cast<char *>( commandLine ), &env, currentPath );
        }
        else if ( request == "EXECUTE_AND_EXIT" )
        {
            if ( receiver.parts() != 2 )
                return fallback.complete( "Invalid message length." );
            llvm::StringRef const commandLine = receiver.getPart( 1 );
            // Running the compiler is implied.
            char const compiler[] = "compiler";
            char * const buffer = static_cast<char *>( alloca( sizeof(compiler) + commandLine.size() + 1 ) );
            std::memcpy( buffer, compiler, sizeof(compiler) - 1 );
            buffer[ sizeof(compiler) - 1 ] = ' ';
            std::memcpy( buffer + sizeof(compiler), commandLine.data(), commandLine.size() );
            buffer[ sizeof(compiler) + commandLine.size() ] = 0;

            return createProcess( compilerExecutable, buffer, &env, currentPath );
        }
        else if ( request == "EXECUTE_GET_OUTPUT" )
        {
            if ( receiver.parts() != 2 )
                return fallback.complete( "Invalid message length." );

            llvm::StringRef const commandLine = receiver.getPart( 1 );
            // Running the compiler is implied.
            char const compiler[] = "compiler";
            char * const buffer = static_cast<char *>( alloca( sizeof(compiler) + commandLine.size() + 1 ) );
            std::memcpy( buffer, compiler, sizeof(compiler) - 1 );
            buffer[ sizeof(compiler) - 1 ] = ' ';
            std::memcpy( buffer + sizeof(compiler), commandLine.data(), commandLine.size() );
            buffer[ sizeof(compiler) + commandLine.size() ] = 0;

            SECURITY_ATTRIBUTES saAttr;
            saAttr.nLength = sizeof(SECURITY_ATTRIBUTES);
            saAttr.bInheritHandle = TRUE;
            saAttr.lpSecurityDescriptor = NULL;

            HANDLE stdOutRead, stdOutWrite;
            CreatePipe( &stdOutRead, &stdOutWrite, &saAttr, 0 );
            SetHandleInformation( stdOutRead, HANDLE_FLAG_INHERIT, 0 );
            HANDLE stdErrRead, stdErrWrite;
            CreatePipe( &stdErrRead, &stdErrWrite, &saAttr, 0 );
            SetHandleInformation( stdErrRead, HANDLE_FLAG_INHERIT, 0 );

            STARTUPINFO startupInfo = { 0 };
            startupInfo.cb = sizeof(STARTUPINFO);
            startupInfo.hStdError = stdErrWrite;
            startupInfo.hStdOutput = stdOutWrite;
            startupInfo.dwFlags |= STARTF_USESTDHANDLES;
            startupInfo.dwFlags |= STARTF_USESHOWWINDOW;
            startupInfo.wShowWindow = SW_HIDE;

            PROCESS_INFORMATION processInfo;

            BOOL const apiResult = CreateProcessA(
                compilerExecutable,
                buffer,
                NULL,
                NULL,
                TRUE,
                0,
                env.createEnvBlock(),
                currentPath,
                &startupInfo,
                &processInfo
            );

            if ( apiResult )
            {
                std::string retcodeStr;
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                {
                    int result;
                    GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                    retcodeStr = std::to_string( result );
                    msgSender.addPart( retcodeStr.data(), retcodeStr.size() );
                }
                DWORD stdOutSize;
                std::unique_ptr<char []> stdOut( getPipeData( stdOutRead, stdOutSize ) );
                msgSender.addPart( stdOut.get(), stdOutSize );
                DWORD stdErrSize;
                std::unique_ptr<char []> stdErr( getPipeData( stdErrRead, stdErrSize ) );
                msgSender.addPart( stdErr.get(), stdErrSize );
                boost::system::error_code writeError;
                msgSender.send( sock, writeError );
                if ( writeError )
                {
                    std::stringstream stream;
                    stream << "Failed to send message (" << writeError.message() << ").";
                    return fallback.complete( stream.str() );
                }
                CloseHandle( processInfo.hProcess );
                CloseHandle( processInfo.hThread );
                CloseHandle( stdOutRead );
                CloseHandle( stdErrRead );
                CloseHandle( stdOutWrite );
                CloseHandle( stdErrWrite );
            }
            else
                return fallback.complete( "Failed to create process." );
        }
        else if ( request == "EXIT" )
        {
            if ( receiver.parts() != 4 )
                return fallback.complete( "Invalid message length." );
            
            if ( receiver.getPart( 1 ).size() != 4 )
                return fallback.complete( "Invalid exit code length." );

            llvm::StringRef const stdOut = receiver.getPart( 2 );
            llvm::StringRef const stdErr = receiver.getPart( 3 );

            DWORD written;
            WriteFile( stdOutHandle, stdOut.data(), stdOut.size(), &written, 0 ); 
            WriteFile( stdErrHandle, stdErr.data(), stdErr.size(), &written, 0 ); 

            unsigned char const * data = reinterpret_cast<unsigned char const *>(
                receiver.getPart( 1 ).data() );
            return static_cast<int>( (data[0] << 24) | (data[1] << 16) |
                data[2] << 8 | data[3] );
        }
        else if ( request == "LOCATE_FILES" )
        {
            if ( receiver.parts() <= 1 )
                return fallback.complete( "Invalid message length." );

            std::vector<std::string> files;
            // First search relative to compiler dir, then path.
            PathList pathList;
            char const * const filename = PathFindFileName( compilerExecutable );
            assert( filename != compilerExecutable );
            pathList.push_back( std::string( compilerExecutable, filename - compilerExecutable ) );
            getPath( env, pathList );

            for ( std::size_t part = 1; part < receiver.parts(); ++part )
            {
                llvm::StringRef file = receiver.getPart( part );
                std::string result;
                findOnPath( pathList, file.str(), result );
                files.push_back( result );
                msgSender.addPart( files.back().c_str(), files.back().size() );
            }
            boost::system::error_code writeError;
            msgSender.send( sock, writeError );
            if ( writeError )
            {
                std::stringstream stream;
                stream << "Failed to send message (" << writeError.message() << ").\n";
                return fallback.complete( stream.str() );
            }
        }
        else
        {
            std::stringstream stream;
            stream << "Invalid request (" << request.str() << ").";
            return fallback.complete( stream.str() );
        }
    }
}
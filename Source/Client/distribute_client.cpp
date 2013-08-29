// This is a rewrite of the distribute_client.py script.
// We need these processes to have a small footprint as
// usually dosens of them concurrently.

#include <zmq.h>

#include <cassert>
#include <deque>
#include <iostream>
#include <memory>
#include <string>
#include <sstream>

char const compiler[] = "msvc";
unsigned int compilerSize = sizeof(compiler) / sizeof(compiler[0]) - 1;

void freeBuffer( void * buffer, void * hint )
{
    assert( buffer );
    assert( !hint );
    delete[] buffer;
}

void sendData( void * socket, std::unique_ptr<char []> & buffer, std::size_t size, int sendFlags )
{
    zmq_msg_t outputMsg;
    zmq_msg_init_data( &outputMsg, buffer.release(), size, &freeBuffer, 0 );
    zmq_msg_send( &outputMsg, socket, sendFlags | ZMQ_DONTWAIT );
    zmq_msg_close( &outputMsg );
}

void sendData( void * socket, char const * buffer, std::size_t size, int sendFlags )
{
    zmq_msg_t msg;
    zmq_msg_init_size( &msg, size );
    std::memcpy( zmq_msg_data( &msg ), buffer, size );
    zmq_msg_send( &msg, socket, sendFlags );
    zmq_msg_close( &msg );
}

void sendData( void * socket, std::string const & data, int sendFlags )
{
    sendData( socket, data.data(), data.size(), sendFlags );
}

void pipeToSocket( HANDLE pipe, void * socket, int sendFlags )
{
    DWORD available = 0;
    DWORD inBuffer = 0;
    if ( !PeekNamedPipe( pipe, 0, 0, 0, &available, 0 ) )
        available = 0;

    std::unique_ptr<char []> buffer;
    if ( available )
    {
        buffer.reset( new char[ available ] );
        ReadFile( pipe, buffer.get(), available, &inBuffer, NULL );
    }

    if ( inBuffer )
        sendData( socket, buffer, inBuffer, sendFlags );
    else
    {
        zmq_msg_t outputMsg;
        zmq_msg_init_size( &outputMsg, 0 );
        zmq_msg_send( &outputMsg, socket, sendFlags | ZMQ_DONTWAIT );
        zmq_msg_close( &outputMsg );
    }
}

class MsgReceiver
{
public:
    typedef std::deque<zmq_msg_t> Msgs;

    explicit MsgReceiver( void * socket )
        : socket_( socket ), msgs_( 2 ), parts_( 0 )
    {
        getParts();
    }

    ~MsgReceiver()
    {
        for ( std::size_t msgIndex( 0 ); msgIndex < parts_; ++msgIndex )
            zmq_msg_close( &msgs_[ msgIndex ] );
    }

    std::pair<char const *, std::size_t> getPart( std::size_t index )
    {
        if ( index >= parts_ )
            return std::make_pair<char const *, std::size_t>( 0, 0 );

        zmq_msg_t & msg( msgs_[ index ] );
        char const * const data = static_cast<char *>( zmq_msg_data( &msg ) );
        std::size_t const size = zmq_msg_size( &msg );
        return std::make_pair( data, size );
    }

    void getPart( std::size_t index, char const * * buff, std::size_t * size )
    {
        std::pair<char const *, std::size_t> const result( getPart( index ) );
        if ( buff ) *buff = result.first;
        if ( size ) *size = result.second;
    }

    std::size_t parts() const { return parts_; }

private:
    void getParts()
    {
        if ( msgs_.size() <= parts_ )
            msgs_.resize( 2 * msgs_.size() );
        zmq_msg_t & msg( msgs_[ parts_ ] );
        zmq_msg_init( &msg );
        zmq_msg_recv( &msg, socket_, 0 );
        parts_++;

        int64_t more = 0;
        size_t more_size = sizeof(more);
        int const rc = zmq_getsockopt( socket_, ZMQ_RCVMORE, &more, &more_size );
        if ( more )
            getParts();
    }

private:
    void * socket_;
    Msgs msgs_;
    std::size_t parts_;
};

class ZmqSocket
{
private:
    ZmqSocket( ZmqSocket const & );
    ZmqSocket & operator=( ZmqSocket const & );

public:
    explicit ZmqSocket( void * socket ) : socket_( socket ), connected_( false ) {}

    ZmqSocket( ZmqSocket && other )
    {
        socket_ = other.socket_;
        connected_ = other.connected_;
        endpoint_.swap( other.endpoint_ );
        other.socket_ = 0;
        other.connected_ = false;
    }

    ZmqSocket & operator=( ZmqSocket && other )
    {
        std::swap( socket_, other.socket_ );
        std::swap( connected_, other.connected_ );
        endpoint_.swap( other.endpoint_ );
    }

    ~ZmqSocket()
    {
        disconnect();
        zmq_close( socket_ );
    }

    void connect( std::string const & endpoint )
    {
        disconnect();

        connected_ = true;
        endpoint_ = endpoint;
        zmq_connect( socket_, endpoint_.c_str() );
    }

    void disconnect()
    {
        if ( !connected_ )
            return;
        zmq_disconnect( socket_, endpoint_.c_str() );
        endpoint_.clear();
        connected_ = false;
    }

    void * handle() const { return socket_; }

private:
    void * socket_;
    std::string endpoint_;
    bool connected_;
};

class ZmqContext
{
public:
    ZmqContext() : context_( zmq_ctx_new() ) {}
    ~ZmqContext() { zmq_ctx_destroy( context_ ); }

    ZmqSocket socket( int type ) const { return ZmqSocket( zmq_socket( context_, type ) ); }

private:
    void * context_;
};

int main( int argc, char * argv[] )
{
    ZmqContext context;
    ZmqSocket socket = context.socket( ZMQ_DEALER );

    std::string endpoint( "tcp://localhost:" );
    endpoint.append( argv[1] );
    
    socket.connect( endpoint );

    sendData( socket.handle(), compiler, compilerSize, ZMQ_SNDMORE );

    DWORD const currentPathSize( GetCurrentDirectory( 0, NULL ) );
    std::unique_ptr<char []> currentPathBuffer( new char[ currentPathSize ] );
    GetCurrentDirectory( currentPathSize, currentPathBuffer.get() );
    sendData( socket.handle(), currentPathBuffer, currentPathSize - 1, ZMQ_SNDMORE );

    for ( int arg( 2 ); arg < argc; ++arg )
    {
        sendData( socket.handle(), argv[arg], strlen(argv[arg]), arg < argc - 1 ? ZMQ_SNDMORE : 0 );
    }

    {
        MsgReceiver reply( socket.handle() );
        assert( reply.parts() == 1 );
        std::pair<char const *, std::size_t> data( reply.getPart( 0 ) );
        assert( data.second == 13 );
        assert( memcmp( data.first, "TASK_RECEIVED", data.second ) == 0 );
    }

    while ( true )
    {
        MsgReceiver requestReceiver( socket.handle() );

        assert( requestReceiver.parts() >= 1 );

        char const * request;
        std::size_t requestSize;
        requestReceiver.getPart( 0, &request, &requestSize );

        if ( ( requestSize == 16 ) && strncmp( request, "EXECUTE_AND_EXIT", 16 ) == 0 )
        {
            assert( requestReceiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            requestReceiver.getPart( 1, &commandLine, &commandLineSize );

            // Create a copy on the stack as required by CreateProcess.
            char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
            std::memcpy( buffer, commandLine, commandLineSize );
            buffer[ commandLineSize ] = 0;

            STARTUPINFO startupInfo = { sizeof(startupInfo) };
            PROCESS_INFORMATION processInfo;

            BOOL const apiResult = CreateProcess(
                NULL,
                buffer,
                NULL,
                NULL,
                FALSE,
                CREATE_NEW_PROCESS_GROUP,
                NULL,
                NULL,
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
                std::cerr << "ERROR: CreateProcess()\n";
                return -1;
            }
        }
        else if ( ( requestSize == 18 ) && strncmp( request, "EXECUTE_GET_OUTPUT", 18 ) == 0 )
        {
            assert( requestReceiver.parts() == 2 );
            char const * commandLine;
            std::size_t commandLineSize;
            requestReceiver.getPart( 1, &commandLine, &commandLineSize );

            // Create a copy on the stack as required by CreateProcess.
            char * const buffer = static_cast<char *>( alloca( commandLineSize + 1 ) );
            std::memcpy( buffer, commandLine, commandLineSize );
            buffer[ commandLineSize ] = 0;

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

            BOOL const apiResult = CreateProcess(
                NULL,
                buffer,
                NULL,
                NULL,
                TRUE,
                CREATE_NEW_PROCESS_GROUP,
                NULL,
                NULL,
                &startupInfo,
                &processInfo
            );

            if ( apiResult )
            {
                ::WaitForSingleObject( processInfo.hProcess, INFINITE );
                {
                    int result;
                    GetExitCodeProcess( processInfo.hProcess, reinterpret_cast<LPDWORD>( &result ) );
                    char buffer[20];
                    _itoa( result, buffer, 10 );
                    std::size_t const size( strlen( buffer ) );
                    sendData( socket.handle(), buffer, strlen( buffer ), ZMQ_SNDMORE );
                }

                pipeToSocket( stdOutRead, socket.handle(), ZMQ_SNDMORE );
                pipeToSocket( stdErrRead, socket.handle(), 0 );

                CloseHandle( processInfo.hProcess );
                CloseHandle( processInfo.hThread );
                CloseHandle( stdOutRead );
                CloseHandle( stdErrRead );
                CloseHandle( stdOutWrite );
                CloseHandle( stdErrWrite );
            }
            else
            {
                std::cerr << "ERROR: CreateProcess()\n";
                return -1;
            }
        }
        else if ( ( requestSize == 4 ) && strncmp( request, "EXIT", 4 ) == 0 )
        {
            assert( requestReceiver.parts() == 2 );
            char const * exitCode;
            std::size_t exitCodeSize;
            requestReceiver.getPart( 1, &exitCode, &exitCodeSize );

            char * buffer = static_cast<char *>( _alloca( exitCodeSize + 1 ) );
            std::memcpy( buffer, exitCode, exitCodeSize );
            buffer[ exitCodeSize ] = 0;
            return atoi( buffer );
        }
        else if ( ( requestSize == 9 ) && strncmp( request, "COMPLETED", 9 ) == 0 )
        {
            assert( requestReceiver.parts() == 4 );
            char const * retcode;
            std::size_t retcodeSize;
            requestReceiver.getPart( 1, &retcode, &retcodeSize );

            char * buffer = static_cast<char *>( _alloca( retcodeSize + 1 ) );
            std::memcpy( buffer, retcode, retcodeSize );
            buffer[ retcodeSize ] = 0;
            int const result = atoi( buffer );

            char const * stdOut;
            std::size_t stdOutSize;
            requestReceiver.getPart( 2, &stdOut, &stdOutSize );

            char const * stdErr;
            std::size_t stdErrSize;
            requestReceiver.getPart( 3, &stdErr, &stdErrSize );

            std::cout << std::string( stdOut, stdOutSize );
            if ( stdErrSize )
                std::cerr << std::string( stdErr, stdErrSize );
            return result;
        }
        else if ( ( requestSize == 6 ) && strncmp( request, "GETENV", 6 ) == 0 )
        {
            // TODO
        }
        else
        {
            std::cout << "ERROR: GOT " << std::string( request, requestSize );
            return -1;
        }
    }

    return 0;
}
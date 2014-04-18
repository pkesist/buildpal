////////////////////////////////////////////////////////////////////////////////
//
// Automatically generated - do not edit
//
////////////////////////////////////////////////////////////////////////////////
// ?runDLL@@YAKPAX@Z PROC					; runDLL
// 
// ; 82   : {
// 
0x83, 0xec, 0x1c,                                // 00000 -  sub	 esp, 28			; 0000001cH
// 
// ; 83   :     RunDllParams * params = (RunDllParams *)vpparams;
// ; 84   : #ifdef _WIN64
// ; 85   :     PPEB base = (PPEB)__readgsqword( 0x60 );
// ; 86   : #else
// ; 87   :     PPEB base = (PPEB)__readfsdword( 0x30 );
// ; 88   : #endif
// ; 89   : 
// ; 90   :     PPEB_LDR_DATA baseAddress = (PPEB_LDR_DATA)base->Ldr;
// ; 91   :     LOADLIBRARYA loadLibrary = 0;
// ; 92   :     GETPROCADDRESS getProcAddress = 0;
// ; 93   :     bool const needGetProcAddress = ( params->initFunc != 0 );
// 
0x8b, 0x44, 0x24, 0x20,                          // 00003 -  mov	 eax, DWORD PTR _vpparams$[esp+24]
0x53,                                            // 00007 -  push	 ebx
0x33, 0xdb,                                      // 00008 -  xor	 ebx, ebx
0x39, 0x58, 0x04,                                // 0000a -  cmp	 DWORD PTR [eax+4], ebx
0x64, 0xa1, 0x30, 0x00, 0x00, 0x00,              // 0000d -  mov	 eax, DWORD PTR fs:48
0x55,                                            // 00013 -  push	 ebp
// 
// ; 94   :     PLDR_DATA_TABLE_ENTRY tableEntry  = (PLDR_DATA_TABLE_ENTRY)(baseAddress->InMemoryOrderModuleList.Flink - 1); // Leap of faith cast.
// 
0x8b, 0x40, 0x0c,                                // 00014 -  mov	 eax, DWORD PTR [eax+12]
0x56,                                            // 00017 -  push	 esi
0x8b, 0x70, 0x14,                                // 00018 -  mov	 esi, DWORD PTR [eax+20]
0x0f, 0x95, 0x44, 0x24, 0x0f,                    // 0001b -  setne	 BYTE PTR _needGetProcAddress$1$[esp+40]
0x57,                                            // 00020 -  push	 edi
0xc7, 0x44, 0x24, 0x18, 0x00, 0x00, 0x00, 0x00,  // 00021 -  mov	 DWORD PTR _loadLibrary$1$[esp+44], 0
0x89, 0x5c, 0x24, 0x14,                          // 00029 -  mov	 DWORD PTR _getProcAddress$1$[esp+44], ebx
0x83, 0xee, 0x08,                                // 0002d -  sub	 esi, 8
// 
// ; 95   :     while ( tableEntry )
// 
0x0f, 0x84, 0x53, 0x01, 0x00, 0x00,              // 00030 -  je	 $LN192@runDLL
// $LL17@runDLL:
// 
// ; 96   :     {
// ; 97   :         UNICODE_STRING const baseDLLName = *(UNICODE_STRING *)(tableEntry->Reserved4);
// 
0x8b, 0x4e, 0x30,                                // 00036 -  mov	 ecx, DWORD PTR [esi+48]
0x8b, 0x46, 0x2c,                                // 00039 -  mov	 eax, DWORD PTR [esi+44]
// 
// ; 98   :         if ( isKernel32( baseDLLName.Buffer ) )
// 
0x0f, 0xb7, 0x11,                                // 0003c -  movzx	 edx, WORD PTR [ecx]
0x89, 0x44, 0x24, 0x24,                          // 0003f -  mov	 DWORD PTR _baseDLLName$2[esp+44], eax
0x8d, 0x42, 0xbf,                                // 00043 -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 00046 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 0004a -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 0004d -  jbe	 SHORT $LN27@runDLL
0x8b, 0xc2,                                      // 0004f -  mov	 eax, edx
// $LN27@runDLL:
0x66, 0x83, 0xf8, 0x6b,                          // 00051 -  cmp	 ax, 107			; 0000006bH
0x0f, 0x85, 0x1c, 0x01, 0x00, 0x00,              // 00055 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x02,                          // 0005b -  movzx	 edx, WORD PTR [ecx+2]
0x8d, 0x42, 0xbf,                                // 0005f -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 00062 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 00066 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 00069 -  jbe	 SHORT $LN31@runDLL
0x8b, 0xc2,                                      // 0006b -  mov	 eax, edx
// $LN31@runDLL:
0x66, 0x83, 0xf8, 0x65,                          // 0006d -  cmp	 ax, 101			; 00000065H
0x0f, 0x85, 0x00, 0x01, 0x00, 0x00,              // 00071 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x04,                          // 00077 -  movzx	 edx, WORD PTR [ecx+4]
0x8d, 0x42, 0xbf,                                // 0007b -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 0007e -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 00082 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 00085 -  jbe	 SHORT $LN35@runDLL
0x8b, 0xc2,                                      // 00087 -  mov	 eax, edx
// $LN35@runDLL:
0x66, 0x83, 0xf8, 0x72,                          // 00089 -  cmp	 ax, 114			; 00000072H
0x0f, 0x85, 0xe4, 0x00, 0x00, 0x00,              // 0008d -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x06,                          // 00093 -  movzx	 edx, WORD PTR [ecx+6]
0x8d, 0x42, 0xbf,                                // 00097 -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 0009a -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 0009e -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 000a1 -  jbe	 SHORT $LN39@runDLL
0x8b, 0xc2,                                      // 000a3 -  mov	 eax, edx
// $LN39@runDLL:
0x66, 0x83, 0xf8, 0x6e,                          // 000a5 -  cmp	 ax, 110			; 0000006eH
0x0f, 0x85, 0xc8, 0x00, 0x00, 0x00,              // 000a9 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x08,                          // 000af -  movzx	 edx, WORD PTR [ecx+8]
0x8d, 0x42, 0xbf,                                // 000b3 -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 000b6 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 000ba -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 000bd -  jbe	 SHORT $LN43@runDLL
0x8b, 0xc2,                                      // 000bf -  mov	 eax, edx
// $LN43@runDLL:
0x66, 0x83, 0xf8, 0x65,                          // 000c1 -  cmp	 ax, 101			; 00000065H
0x0f, 0x85, 0xac, 0x00, 0x00, 0x00,              // 000c5 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0a,                          // 000cb -  movzx	 edx, WORD PTR [ecx+10]
0x8d, 0x42, 0xbf,                                // 000cf -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 000d2 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 000d6 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 000d9 -  jbe	 SHORT $LN47@runDLL
0x8b, 0xc2,                                      // 000db -  mov	 eax, edx
// $LN47@runDLL:
0x66, 0x83, 0xf8, 0x6c,                          // 000dd -  cmp	 ax, 108			; 0000006cH
0x0f, 0x85, 0x90, 0x00, 0x00, 0x00,              // 000e1 -  jne	 $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0c,                          // 000e7 -  movzx	 edx, WORD PTR [ecx+12]
0x8d, 0x42, 0xbf,                                // 000eb -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 000ee -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 000f2 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 000f5 -  jbe	 SHORT $LN51@runDLL
0x8b, 0xc2,                                      // 000f7 -  mov	 eax, edx
// $LN51@runDLL:
0x66, 0x83, 0xf8, 0x33,                          // 000f9 -  cmp	 ax, 51			; 00000033H
0x75, 0x78,                                      // 000fd -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x0e,                          // 000ff -  movzx	 edx, WORD PTR [ecx+14]
0x8d, 0x42, 0xbf,                                // 00103 -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 00106 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 0010a -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 0010d -  jbe	 SHORT $LN55@runDLL
0x8b, 0xc2,                                      // 0010f -  mov	 eax, edx
// $LN55@runDLL:
0x66, 0x83, 0xf8, 0x32,                          // 00111 -  cmp	 ax, 50			; 00000032H
0x75, 0x60,                                      // 00115 -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x10,                          // 00117 -  movzx	 edx, WORD PTR [ecx+16]
0x8d, 0x42, 0xbf,                                // 0011b -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 0011e -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 00122 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 00125 -  jbe	 SHORT $LN59@runDLL
0x8b, 0xc2,                                      // 00127 -  mov	 eax, edx
// $LN59@runDLL:
0x66, 0x83, 0xf8, 0x2e,                          // 00129 -  cmp	 ax, 46			; 0000002eH
0x75, 0x48,                                      // 0012d -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x12,                          // 0012f -  movzx	 edx, WORD PTR [ecx+18]
0x8d, 0x42, 0xbf,                                // 00133 -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 00136 -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 0013a -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 0013d -  jbe	 SHORT $LN63@runDLL
0x8b, 0xc2,                                      // 0013f -  mov	 eax, edx
// $LN63@runDLL:
0x66, 0x83, 0xf8, 0x64,                          // 00141 -  cmp	 ax, 100			; 00000064H
0x75, 0x30,                                      // 00145 -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x51, 0x14,                          // 00147 -  movzx	 edx, WORD PTR [ecx+20]
0x8d, 0x42, 0xbf,                                // 0014b -  lea	 eax, DWORD PTR [edx-65]
0x66, 0x83, 0xf8, 0x19,                          // 0014e -  cmp	 ax, 25			; 00000019H
0x8d, 0x42, 0x20,                                // 00152 -  lea	 eax, DWORD PTR [edx+32]
0x76, 0x02,                                      // 00155 -  jbe	 SHORT $LN67@runDLL
0x8b, 0xc2,                                      // 00157 -  mov	 eax, edx
// $LN67@runDLL:
0x66, 0x83, 0xf8, 0x6c,                          // 00159 -  cmp	 ax, 108			; 0000006cH
0x75, 0x18,                                      // 0015d -  jne	 SHORT $LN22@runDLL
0x0f, 0xb7, 0x49, 0x16,                          // 0015f -  movzx	 ecx, WORD PTR [ecx+22]
0x8d, 0x41, 0xbf,                                // 00163 -  lea	 eax, DWORD PTR [ecx-65]
0x66, 0x83, 0xf8, 0x19,                          // 00166 -  cmp	 ax, 25			; 00000019H
0x8d, 0x41, 0x20,                                // 0016a -  lea	 eax, DWORD PTR [ecx+32]
0x76, 0x02,                                      // 0016d -  jbe	 SHORT $LN71@runDLL
0x8b, 0xc1,                                      // 0016f -  mov	 eax, ecx
// $LN71@runDLL:
0x66, 0x83, 0xf8, 0x6c,                          // 00171 -  cmp	 ax, 108			; 0000006cH
0x74, 0x1f,                                      // 00175 -  je	 SHORT $LN186@runDLL
// $LN22@runDLL:
// 
// ; 126  :             }
// ; 127  :             break;
// ; 128  :         }
// ; 129  :         if ( tableEntry->InMemoryOrderLinks.Flink == 0 )
// 
0x8b, 0x46, 0x08,                                // 00177 -  mov	 eax, DWORD PTR [esi+8]
0x85, 0xc0,                                      // 0017a -  test	 eax, eax
0x74, 0x0b,                                      // 0017c -  je	 SHORT $LN192@runDLL
// 
// ; 130  :             break;
// ; 131  :         tableEntry = (PLDR_DATA_TABLE_ENTRY)(tableEntry->InMemoryOrderLinks.Flink - 1);
// 
0x8d, 0x70, 0xf8,                                // 0017e -  lea	 esi, DWORD PTR [eax-8]
0x85, 0xf6,                                      // 00181 -  test	 esi, esi
0x0f, 0x85, 0xad, 0xfe, 0xff, 0xff,              // 00183 -  jne	 $LL17@runDLL
// $LN192@runDLL:
0x5f,                                            // 00189 -  pop	 edi
0x5e,                                            // 0018a -  pop	 esi
0x5d,                                            // 0018b -  pop	 ebp
// 
// ; 134  :         return -2;
// 
0xb8, 0xfe, 0xff, 0xff, 0xff,                    // 0018c -  mov	 eax, -2			; fffffffeH
0x5b,                                            // 00191 -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 00192 -  add	 esp, 28			; 0000001cH
0xc3,                                            // 00195 -  ret	 0
// $LN186@runDLL:
// 
// ; 99   :         {
// ; 100  :             PBYTE dllBase = (PBYTE)tableEntry->DllBase;
// 
0x8b, 0x76, 0x18,                                // 00196 -  mov	 esi, DWORD PTR [esi+24]
// 
// ; 101  :             PIMAGE_DOS_HEADER dos_header = (PIMAGE_DOS_HEADER)dllBase;
// ; 102  :             PIMAGE_NT_HEADERS nt_headers = (PIMAGE_NT_HEADERS)(dllBase + dos_header->e_lfanew);
// ; 103  :             PIMAGE_DATA_DIRECTORY data_dir = (PIMAGE_DATA_DIRECTORY)(&nt_headers->OptionalHeader.DataDirectory[ IMAGE_DIRECTORY_ENTRY_EXPORT ]);
// ; 104  :             PIMAGE_EXPORT_DIRECTORY export_dir = (PIMAGE_EXPORT_DIRECTORY)(dllBase + data_dir->VirtualAddress);
// ; 105  :             DWORD * nameArray = (DWORD *)(dllBase + export_dir->AddressOfNames);
// ; 106  :             WORD * ordArray = (WORD *)( dllBase + export_dir->AddressOfNameOrdinals);
// ; 107  :             unsigned int counter( 0 );
// 
0x33, 0xff,                                      // 00199 -  xor	 edi, edi
0x8b, 0x46, 0x3c,                                // 0019b -  mov	 eax, DWORD PTR [esi+60]
0x8b, 0x4c, 0x30, 0x78,                          // 0019e -  mov	 ecx, DWORD PTR [eax+esi+120]
0x8b, 0x44, 0x31, 0x24,                          // 001a2 -  mov	 eax, DWORD PTR [ecx+esi+36]
0x8b, 0x6c, 0x31, 0x20,                          // 001a6 -  mov	 ebp, DWORD PTR [ecx+esi+32]
0x03, 0xce,                                      // 001aa -  add	 ecx, esi
0x03, 0xc6,                                      // 001ac -  add	 eax, esi
0x89, 0x44, 0x24, 0x1c,                          // 001ae -  mov	 DWORD PTR _ordArray$1$[esp+44], eax
0x8b, 0x41, 0x14,                                // 001b2 -  mov	 eax, DWORD PTR [ecx+20]
0x03, 0xee,                                      // 001b5 -  add	 ebp, esi
0x89, 0x4c, 0x24, 0x20,                          // 001b7 -  mov	 DWORD PTR _export_dir$1$[esp+44], ecx
0x89, 0x44, 0x24, 0x24,                          // 001bb -  mov	 DWORD PTR $T1[esp+44], eax
// 
// ; 108  :             while ( ( counter < export_dir->NumberOfFunctions ) &&
// ; 109  :                 ( !loadLibrary || ( needGetProcAddress && !getProcAddress ) ) )
// 
0x85, 0xc0,                                      // 001bf -  test	 eax, eax
0x74, 0xc6,                                      // 001c1 -  je	 SHORT $LN192@runDLL
0x33, 0xc0,                                      // 001c3 -  xor	 eax, eax
// $LL14@runDLL:
0x85, 0xc0,                                      // 001c5 -  test	 eax, eax
0x74, 0x14,                                      // 001c7 -  je	 SHORT $LN12@runDLL
0x8a, 0x4c, 0x24, 0x13,                          // 001c9 -  mov	 cl, BYTE PTR _needGetProcAddress$1$[esp+44]
0x84, 0xc9,                                      // 001cd -  test	 cl, cl
0x0f, 0x84, 0xab, 0x02, 0x00, 0x00,              // 001cf -  je	 $LN13@runDLL
0x85, 0xdb,                                      // 001d5 -  test	 ebx, ebx
0x0f, 0x85, 0xa3, 0x02, 0x00, 0x00,              // 001d7 -  jne	 $LN13@runDLL
// $LN12@runDLL:
// 
// ; 110  :             {
// ; 111  :                 char const * name = (char const *)(dllBase + *nameArray);
// 
0x8b, 0x55, 0x00,                                // 001dd -  mov	 edx, DWORD PTR [ebp]
0x03, 0xd6,                                      // 001e0 -  add	 edx, esi
// 
// ; 112  :                 bool const gpa = isGetProcAddress( name );
// 
0x8a, 0x1a,                                      // 001e2 -  mov	 bl, BYTE PTR [edx]
0x8d, 0x43, 0xbf,                                // 001e4 -  lea	 eax, DWORD PTR [ebx-65]
0x3c, 0x19,                                      // 001e7 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc3,                                // 001e9 -  movsx	 eax, bl
0x77, 0x03,                                      // 001ec -  ja	 SHORT $LN79@runDLL
0x83, 0xc0, 0x20,                                // 001ee -  add	 eax, 32			; 00000020H
// $LN79@runDLL:
0x3c, 0x67,                                      // 001f1 -  cmp	 al, 103			; 00000067H
0x0f, 0x85, 0x20, 0x01, 0x00, 0x00,              // 001f3 -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x01,                                // 001f9 -  mov	 cl, BYTE PTR [edx+1]
0x8d, 0x41, 0xbf,                                // 001fc -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 001ff -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00201 -  movsx	 eax, cl
0x77, 0x03,                                      // 00204 -  ja	 SHORT $LN83@runDLL
0x83, 0xc0, 0x20,                                // 00206 -  add	 eax, 32			; 00000020H
// $LN83@runDLL:
0x3c, 0x65,                                      // 00209 -  cmp	 al, 101			; 00000065H
0x0f, 0x85, 0x08, 0x01, 0x00, 0x00,              // 0020b -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x02,                                // 00211 -  mov	 cl, BYTE PTR [edx+2]
0x8d, 0x41, 0xbf,                                // 00214 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00217 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00219 -  movsx	 eax, cl
0x77, 0x03,                                      // 0021c -  ja	 SHORT $LN87@runDLL
0x83, 0xc0, 0x20,                                // 0021e -  add	 eax, 32			; 00000020H
// $LN87@runDLL:
0x3c, 0x74,                                      // 00221 -  cmp	 al, 116			; 00000074H
0x0f, 0x85, 0xf0, 0x00, 0x00, 0x00,              // 00223 -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x03,                                // 00229 -  mov	 cl, BYTE PTR [edx+3]
0x8d, 0x41, 0xbf,                                // 0022c -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0022f -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00231 -  movsx	 eax, cl
0x77, 0x03,                                      // 00234 -  ja	 SHORT $LN91@runDLL
0x83, 0xc0, 0x20,                                // 00236 -  add	 eax, 32			; 00000020H
// $LN91@runDLL:
0x3c, 0x70,                                      // 00239 -  cmp	 al, 112			; 00000070H
0x0f, 0x85, 0xd8, 0x00, 0x00, 0x00,              // 0023b -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x04,                                // 00241 -  mov	 cl, BYTE PTR [edx+4]
0x8d, 0x41, 0xbf,                                // 00244 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00247 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00249 -  movsx	 eax, cl
0x77, 0x03,                                      // 0024c -  ja	 SHORT $LN95@runDLL
0x83, 0xc0, 0x20,                                // 0024e -  add	 eax, 32			; 00000020H
// $LN95@runDLL:
0x3c, 0x72,                                      // 00251 -  cmp	 al, 114			; 00000072H
0x0f, 0x85, 0xc0, 0x00, 0x00, 0x00,              // 00253 -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x05,                                // 00259 -  mov	 cl, BYTE PTR [edx+5]
0x8d, 0x41, 0xbf,                                // 0025c -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0025f -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00261 -  movsx	 eax, cl
0x77, 0x03,                                      // 00264 -  ja	 SHORT $LN99@runDLL
0x83, 0xc0, 0x20,                                // 00266 -  add	 eax, 32			; 00000020H
// $LN99@runDLL:
0x3c, 0x6f,                                      // 00269 -  cmp	 al, 111			; 0000006fH
0x0f, 0x85, 0xa8, 0x00, 0x00, 0x00,              // 0026b -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x06,                                // 00271 -  mov	 cl, BYTE PTR [edx+6]
0x8d, 0x41, 0xbf,                                // 00274 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00277 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00279 -  movsx	 eax, cl
0x77, 0x03,                                      // 0027c -  ja	 SHORT $LN103@runDLL
0x83, 0xc0, 0x20,                                // 0027e -  add	 eax, 32			; 00000020H
// $LN103@runDLL:
0x3c, 0x63,                                      // 00281 -  cmp	 al, 99			; 00000063H
0x0f, 0x85, 0x90, 0x00, 0x00, 0x00,              // 00283 -  jne	 $LN74@runDLL
0x8a, 0x4a, 0x07,                                // 00289 -  mov	 cl, BYTE PTR [edx+7]
0x8d, 0x41, 0xbf,                                // 0028c -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0028f -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00291 -  movsx	 eax, cl
0x77, 0x03,                                      // 00294 -  ja	 SHORT $LN107@runDLL
0x83, 0xc0, 0x20,                                // 00296 -  add	 eax, 32			; 00000020H
// $LN107@runDLL:
0x3c, 0x61,                                      // 00299 -  cmp	 al, 97			; 00000061H
0x75, 0x7c,                                      // 0029b -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x08,                                // 0029d -  mov	 cl, BYTE PTR [edx+8]
0x8d, 0x41, 0xbf,                                // 002a0 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 002a3 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 002a5 -  movsx	 eax, cl
0x77, 0x03,                                      // 002a8 -  ja	 SHORT $LN111@runDLL
0x83, 0xc0, 0x20,                                // 002aa -  add	 eax, 32			; 00000020H
// $LN111@runDLL:
0x3c, 0x64,                                      // 002ad -  cmp	 al, 100			; 00000064H
0x75, 0x68,                                      // 002af -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x09,                                // 002b1 -  mov	 cl, BYTE PTR [edx+9]
0x8d, 0x41, 0xbf,                                // 002b4 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 002b7 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 002b9 -  movsx	 eax, cl
0x77, 0x03,                                      // 002bc -  ja	 SHORT $LN115@runDLL
0x83, 0xc0, 0x20,                                // 002be -  add	 eax, 32			; 00000020H
// $LN115@runDLL:
0x3c, 0x64,                                      // 002c1 -  cmp	 al, 100			; 00000064H
0x75, 0x54,                                      // 002c3 -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x0a,                                // 002c5 -  mov	 cl, BYTE PTR [edx+10]
0x8d, 0x41, 0xbf,                                // 002c8 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 002cb -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 002cd -  movsx	 eax, cl
0x77, 0x03,                                      // 002d0 -  ja	 SHORT $LN119@runDLL
0x83, 0xc0, 0x20,                                // 002d2 -  add	 eax, 32			; 00000020H
// $LN119@runDLL:
0x3c, 0x72,                                      // 002d5 -  cmp	 al, 114			; 00000072H
0x75, 0x40,                                      // 002d7 -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x0b,                                // 002d9 -  mov	 cl, BYTE PTR [edx+11]
0x8d, 0x41, 0xbf,                                // 002dc -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 002df -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 002e1 -  movsx	 eax, cl
0x77, 0x03,                                      // 002e4 -  ja	 SHORT $LN123@runDLL
0x83, 0xc0, 0x20,                                // 002e6 -  add	 eax, 32			; 00000020H
// $LN123@runDLL:
0x3c, 0x65,                                      // 002e9 -  cmp	 al, 101			; 00000065H
0x75, 0x2c,                                      // 002eb -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x0c,                                // 002ed -  mov	 cl, BYTE PTR [edx+12]
0x8d, 0x41, 0xbf,                                // 002f0 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 002f3 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 002f5 -  movsx	 eax, cl
0x77, 0x03,                                      // 002f8 -  ja	 SHORT $LN127@runDLL
0x83, 0xc0, 0x20,                                // 002fa -  add	 eax, 32			; 00000020H
// $LN127@runDLL:
0x3c, 0x73,                                      // 002fd -  cmp	 al, 115			; 00000073H
0x75, 0x18,                                      // 002ff -  jne	 SHORT $LN74@runDLL
0x8a, 0x4a, 0x0d,                                // 00301 -  mov	 cl, BYTE PTR [edx+13]
0x8d, 0x41, 0xbf,                                // 00304 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00307 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00309 -  movsx	 eax, cl
0x77, 0x03,                                      // 0030c -  ja	 SHORT $LN131@runDLL
0x83, 0xc0, 0x20,                                // 0030e -  add	 eax, 32			; 00000020H
// $LN131@runDLL:
0x3c, 0x73,                                      // 00311 -  cmp	 al, 115			; 00000073H
0x75, 0x04,                                      // 00313 -  jne	 SHORT $LN74@runDLL
0xb5, 0x01,                                      // 00315 -  mov	 ch, 1
0xeb, 0x02,                                      // 00317 -  jmp	 SHORT $LN75@runDLL
// $LN74@runDLL:
0x32, 0xed,                                      // 00319 -  xor	 ch, ch
// $LN75@runDLL:
// 
// ; 113  :                 bool const ll = isLoadLibrary( name );
// 
0x8d, 0x43, 0xbf,                                // 0031b -  lea	 eax, DWORD PTR [ebx-65]
0x3c, 0x19,                                      // 0031e -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc3,                                // 00320 -  movsx	 eax, bl
0x77, 0x03,                                      // 00323 -  ja	 SHORT $LN139@runDLL
0x83, 0xc0, 0x20,                                // 00325 -  add	 eax, 32			; 00000020H
// $LN139@runDLL:
0x3c, 0x6c,                                      // 00328 -  cmp	 al, 108			; 0000006cH
0x0f, 0x85, 0xf0, 0x00, 0x00, 0x00,              // 0032a -  jne	 $LN134@runDLL
0x8a, 0x4a, 0x01,                                // 00330 -  mov	 cl, BYTE PTR [edx+1]
0x8d, 0x41, 0xbf,                                // 00333 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00336 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00338 -  movsx	 eax, cl
0x77, 0x03,                                      // 0033b -  ja	 SHORT $LN143@runDLL
0x83, 0xc0, 0x20,                                // 0033d -  add	 eax, 32			; 00000020H
// $LN143@runDLL:
0x3c, 0x6f,                                      // 00340 -  cmp	 al, 111			; 0000006fH
0x0f, 0x85, 0xd8, 0x00, 0x00, 0x00,              // 00342 -  jne	 $LN134@runDLL
0x8a, 0x4a, 0x02,                                // 00348 -  mov	 cl, BYTE PTR [edx+2]
0x8d, 0x41, 0xbf,                                // 0034b -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0034e -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00350 -  movsx	 eax, cl
0x77, 0x03,                                      // 00353 -  ja	 SHORT $LN147@runDLL
0x83, 0xc0, 0x20,                                // 00355 -  add	 eax, 32			; 00000020H
// $LN147@runDLL:
0x3c, 0x61,                                      // 00358 -  cmp	 al, 97			; 00000061H
0x0f, 0x85, 0xc0, 0x00, 0x00, 0x00,              // 0035a -  jne	 $LN134@runDLL
0x8a, 0x4a, 0x03,                                // 00360 -  mov	 cl, BYTE PTR [edx+3]
0x8d, 0x41, 0xbf,                                // 00363 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00366 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00368 -  movsx	 eax, cl
0x77, 0x03,                                      // 0036b -  ja	 SHORT $LN151@runDLL
0x83, 0xc0, 0x20,                                // 0036d -  add	 eax, 32			; 00000020H
// $LN151@runDLL:
0x3c, 0x64,                                      // 00370 -  cmp	 al, 100			; 00000064H
0x0f, 0x85, 0xa8, 0x00, 0x00, 0x00,              // 00372 -  jne	 $LN134@runDLL
0x8a, 0x4a, 0x04,                                // 00378 -  mov	 cl, BYTE PTR [edx+4]
0x8d, 0x41, 0xbf,                                // 0037b -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0037e -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00380 -  movsx	 eax, cl
0x77, 0x03,                                      // 00383 -  ja	 SHORT $LN155@runDLL
0x83, 0xc0, 0x20,                                // 00385 -  add	 eax, 32			; 00000020H
// $LN155@runDLL:
0x3c, 0x6c,                                      // 00388 -  cmp	 al, 108			; 0000006cH
0x0f, 0x85, 0x90, 0x00, 0x00, 0x00,              // 0038a -  jne	 $LN134@runDLL
0x8a, 0x4a, 0x05,                                // 00390 -  mov	 cl, BYTE PTR [edx+5]
0x8d, 0x41, 0xbf,                                // 00393 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 00396 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00398 -  movsx	 eax, cl
0x77, 0x03,                                      // 0039b -  ja	 SHORT $LN159@runDLL
0x83, 0xc0, 0x20,                                // 0039d -  add	 eax, 32			; 00000020H
// $LN159@runDLL:
0x3c, 0x69,                                      // 003a0 -  cmp	 al, 105			; 00000069H
0x75, 0x7c,                                      // 003a2 -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x06,                                // 003a4 -  mov	 cl, BYTE PTR [edx+6]
0x8d, 0x41, 0xbf,                                // 003a7 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 003aa -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 003ac -  movsx	 eax, cl
0x77, 0x03,                                      // 003af -  ja	 SHORT $LN163@runDLL
0x83, 0xc0, 0x20,                                // 003b1 -  add	 eax, 32			; 00000020H
// $LN163@runDLL:
0x3c, 0x62,                                      // 003b4 -  cmp	 al, 98			; 00000062H
0x75, 0x68,                                      // 003b6 -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x07,                                // 003b8 -  mov	 cl, BYTE PTR [edx+7]
0x8d, 0x41, 0xbf,                                // 003bb -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 003be -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 003c0 -  movsx	 eax, cl
0x77, 0x03,                                      // 003c3 -  ja	 SHORT $LN167@runDLL
0x83, 0xc0, 0x20,                                // 003c5 -  add	 eax, 32			; 00000020H
// $LN167@runDLL:
0x3c, 0x72,                                      // 003c8 -  cmp	 al, 114			; 00000072H
0x75, 0x54,                                      // 003ca -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x08,                                // 003cc -  mov	 cl, BYTE PTR [edx+8]
0x8d, 0x41, 0xbf,                                // 003cf -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 003d2 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 003d4 -  movsx	 eax, cl
0x77, 0x03,                                      // 003d7 -  ja	 SHORT $LN171@runDLL
0x83, 0xc0, 0x20,                                // 003d9 -  add	 eax, 32			; 00000020H
// $LN171@runDLL:
0x3c, 0x61,                                      // 003dc -  cmp	 al, 97			; 00000061H
0x75, 0x40,                                      // 003de -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x09,                                // 003e0 -  mov	 cl, BYTE PTR [edx+9]
0x8d, 0x41, 0xbf,                                // 003e3 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 003e6 -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 003e8 -  movsx	 eax, cl
0x77, 0x03,                                      // 003eb -  ja	 SHORT $LN175@runDLL
0x83, 0xc0, 0x20,                                // 003ed -  add	 eax, 32			; 00000020H
// $LN175@runDLL:
0x3c, 0x72,                                      // 003f0 -  cmp	 al, 114			; 00000072H
0x75, 0x2c,                                      // 003f2 -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x0a,                                // 003f4 -  mov	 cl, BYTE PTR [edx+10]
0x8d, 0x41, 0xbf,                                // 003f7 -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 003fa -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 003fc -  movsx	 eax, cl
0x77, 0x03,                                      // 003ff -  ja	 SHORT $LN179@runDLL
0x83, 0xc0, 0x20,                                // 00401 -  add	 eax, 32			; 00000020H
// $LN179@runDLL:
0x3c, 0x79,                                      // 00404 -  cmp	 al, 121			; 00000079H
0x75, 0x18,                                      // 00406 -  jne	 SHORT $LN134@runDLL
0x8a, 0x4a, 0x0b,                                // 00408 -  mov	 cl, BYTE PTR [edx+11]
0x8d, 0x41, 0xbf,                                // 0040b -  lea	 eax, DWORD PTR [ecx-65]
0x3c, 0x19,                                      // 0040e -  cmp	 al, 25			; 00000019H
0x0f, 0xbe, 0xc1,                                // 00410 -  movsx	 eax, cl
0x77, 0x03,                                      // 00413 -  ja	 SHORT $LN183@runDLL
0x83, 0xc0, 0x20,                                // 00415 -  add	 eax, 32			; 00000020H
// $LN183@runDLL:
0x3c, 0x61,                                      // 00418 -  cmp	 al, 97			; 00000061H
0x75, 0x04,                                      // 0041a -  jne	 SHORT $LN134@runDLL
0xb2, 0x01,                                      // 0041c -  mov	 dl, 1
0xeb, 0x02,                                      // 0041e -  jmp	 SHORT $LN135@runDLL
// $LN134@runDLL:
0x32, 0xd2,                                      // 00420 -  xor	 dl, dl
// $LN135@runDLL:
// 
// ; 114  :                 if ( ( needGetProcAddress && gpa ) || ll )
// 
0x8a, 0x4c, 0x24, 0x13,                          // 00422 -  mov	 cl, BYTE PTR _needGetProcAddress$1$[esp+44]
0x84, 0xc9,                                      // 00426 -  test	 cl, cl
0x74, 0x04,                                      // 00428 -  je	 SHORT $LN9@runDLL
0x84, 0xed,                                      // 0042a -  test	 ch, ch
0x75, 0x04,                                      // 0042c -  jne	 SHORT $LN10@runDLL
// $LN9@runDLL:
0x84, 0xd2,                                      // 0042e -  test	 dl, dl
0x74, 0x33,                                      // 00430 -  je	 SHORT $LN196@runDLL
// $LN10@runDLL:
// 
// ; 115  :                 {
// ; 116  :                     DWORD * address = (DWORD *)(dllBase + export_dir->AddressOfFunctions);
// ; 117  :                     address += *ordArray;
// 
0x8b, 0x44, 0x24, 0x1c,                          // 00432 -  mov	 eax, DWORD PTR _ordArray$1$[esp+44]
0x0f, 0xb7, 0x08,                                // 00436 -  movzx	 ecx, WORD PTR [eax]
0x8b, 0x44, 0x24, 0x20,                          // 00439 -  mov	 eax, DWORD PTR _export_dir$1$[esp+44]
0x8b, 0x40, 0x1c,                                // 0043d -  mov	 eax, DWORD PTR [eax+28]
0x8d, 0x04, 0x88,                                // 00440 -  lea	 eax, DWORD PTR [eax+ecx*4]
// 
// ; 120  :                     else
// 
0x8a, 0x4c, 0x24, 0x13,                          // 00443 -  mov	 cl, BYTE PTR _needGetProcAddress$1$[esp+44]
0x84, 0xd2,                                      // 00447 -  test	 dl, dl
0x74, 0x0b,                                      // 00449 -  je	 SHORT $LN8@runDLL
// 
// ; 118  :                     if ( ll )
// ; 119  :                         loadLibrary = (LOADLIBRARYA)(dllBase + *address);
// 
0x8b, 0x04, 0x30,                                // 0044b -  mov	 eax, DWORD PTR [eax+esi]
0x03, 0xc6,                                      // 0044e -  add	 eax, esi
0x89, 0x44, 0x24, 0x18,                          // 00450 -  mov	 DWORD PTR _loadLibrary$1$[esp+44], eax
// 
// ; 120  :                     else
// 
0xeb, 0x13,                                      // 00454 -  jmp	 SHORT $LN197@runDLL
// $LN8@runDLL:
// 
// ; 121  :                         getProcAddress = (GETPROCADDRESS)(dllBase + *address);
// 
0x8b, 0x1c, 0x30,                                // 00456 -  mov	 ebx, DWORD PTR [eax+esi]
0x8b, 0x44, 0x24, 0x18,                          // 00459 -  mov	 eax, DWORD PTR _loadLibrary$1$[esp+44]
0x03, 0xde,                                      // 0045d -  add	 ebx, esi
0x89, 0x5c, 0x24, 0x14,                          // 0045f -  mov	 DWORD PTR _getProcAddress$1$[esp+44], ebx
0xeb, 0x08,                                      // 00463 -  jmp	 SHORT $LN7@runDLL
// $LN196@runDLL:
0x8b, 0x44, 0x24, 0x18,                          // 00465 -  mov	 eax, DWORD PTR _loadLibrary$1$[esp+44]
// $LN197@runDLL:
0x8b, 0x5c, 0x24, 0x14,                          // 00469 -  mov	 ebx, DWORD PTR _getProcAddress$1$[esp+44]
// $LN7@runDLL:
// 
// ; 122  :                 }
// ; 123  :                 ++nameArray;
// ; 124  :                 ++ordArray;
// 
0x83, 0x44, 0x24, 0x1c, 0x02,                    // 0046d -  add	 DWORD PTR _ordArray$1$[esp+44], 2
// 
// ; 125  :                 ++counter;
// 
0x47,                                            // 00472 -  inc	 edi
0x83, 0xc5, 0x04,                                // 00473 -  add	 ebp, 4
0x3b, 0x7c, 0x24, 0x24,                          // 00476 -  cmp	 edi, DWORD PTR $T1[esp+44]
0x0f, 0x82, 0x45, 0xfd, 0xff, 0xff,              // 0047a -  jb	 $LL14@runDLL
// $LN13@runDLL:
// 
// ; 132  :     }
// ; 133  :     if ( !loadLibrary )
// 
0x85, 0xc0,                                      // 00480 -  test	 eax, eax
0x0f, 0x84, 0x01, 0xfd, 0xff, 0xff,              // 00482 -  je	 $LN192@runDLL
// 
// ; 135  :     if ( needGetProcAddress && !getProcAddress )
// 
0x84, 0xc9,                                      // 00488 -  test	 cl, cl
0x74, 0x11,                                      // 0048a -  je	 SHORT $LN4@runDLL
0x85, 0xdb,                                      // 0048c -  test	 ebx, ebx
0x75, 0x0d,                                      // 0048e -  jne	 SHORT $LN4@runDLL
// 
// ; 136  :         return -3;
// 
0x5f,                                            // 00490 -  pop	 edi
0x5e,                                            // 00491 -  pop	 esi
0x5d,                                            // 00492 -  pop	 ebp
0xb8, 0xfd, 0xff, 0xff, 0xff,                    // 00493 -  mov	 eax, -3			; fffffffdH
0x5b,                                            // 00498 -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 00499 -  add	 esp, 28			; 0000001cH
0xc3,                                            // 0049c -  ret	 0
// $LN4@runDLL:
// 
// ; 137  :     HMODULE mydll = loadLibrary( params->dllPath );
// 
0x8b, 0x6c, 0x24, 0x30,                          // 0049d -  mov	 ebp, DWORD PTR _vpparams$[esp+40]
0xff, 0x75, 0x00,                                // 004a1 -  push	 DWORD PTR [ebp]
0xff, 0xd0,                                      // 004a4 -  call	 eax
0x8b, 0xc8,                                      // 004a6 -  mov	 ecx, eax
// 
// ; 138  :     if ( !mydll )
// 
0x85, 0xc9,                                      // 004a8 -  test	 ecx, ecx
0x75, 0x0d,                                      // 004aa -  jne	 SHORT $LN3@runDLL
// 
// ; 139  :         return -4;
// 
0x5f,                                            // 004ac -  pop	 edi
0x5e,                                            // 004ad -  pop	 esi
0x5d,                                            // 004ae -  pop	 ebp
0xb8, 0xfc, 0xff, 0xff, 0xff,                    // 004af -  mov	 eax, -4			; fffffffcH
0x5b,                                            // 004b4 -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 004b5 -  add	 esp, 28			; 0000001cH
0xc3,                                            // 004b8 -  ret	 0
// $LN3@runDLL:
// 
// ; 140  :     if ( params->initFunc )
// 
0x8b, 0x45, 0x04,                                // 004b9 -  mov	 eax, DWORD PTR [ebp+4]
0x85, 0xc0,                                      // 004bc -  test	 eax, eax
0x74, 0x22,                                      // 004be -  je	 SHORT $LN2@runDLL
// 
// ; 141  :     {
// ; 142  :         typedef DWORD (WINAPI *InitFunc)( void * );
// ; 143  :         InitFunc initFunc = (InitFunc)getProcAddress( mydll, params->initFunc );
// 
0x50,                                            // 004c0 -  push	 eax
0x51,                                            // 004c1 -  push	 ecx
0xff, 0xd3,                                      // 004c2 -  call	 ebx
// 
// ; 144  :         if ( !initFunc )
// 
0x85, 0xc0,                                      // 004c4 -  test	 eax, eax
0x75, 0x0d,                                      // 004c6 -  jne	 SHORT $LN1@runDLL
// 
// ; 145  :             return -5;
// 
0x5f,                                            // 004c8 -  pop	 edi
0x5e,                                            // 004c9 -  pop	 esi
0x5d,                                            // 004ca -  pop	 ebp
0xb8, 0xfb, 0xff, 0xff, 0xff,                    // 004cb -  mov	 eax, -5			; fffffffbH
0x5b,                                            // 004d0 -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 004d1 -  add	 esp, 28			; 0000001cH
0xc3,                                            // 004d4 -  ret	 0
// $LN1@runDLL:
// 
// ; 146  :         return initFunc( params->initArgs );
// 
0xff, 0x75, 0x08,                                // 004d5 -  push	 DWORD PTR [ebp+8]
0xff, 0xd0,                                      // 004d8 -  call	 eax
0x5f,                                            // 004da -  pop	 edi
0x5e,                                            // 004db -  pop	 esi
0x5d,                                            // 004dc -  pop	 ebp
0x5b,                                            // 004dd -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 004de -  add	 esp, 28			; 0000001cH
0xc3,                                            // 004e1 -  ret	 0
// $LN2@runDLL:
0x5f,                                            // 004e2 -  pop	 edi
0x5e,                                            // 004e3 -  pop	 esi
0x5d,                                            // 004e4 -  pop	 ebp
// 
// ; 147  :     }
// ; 148  :     return 0;
// 
0x33, 0xc0,                                      // 004e5 -  xor	 eax, eax
0x5b,                                            // 004e7 -  pop	 ebx
// 
// ; 149  : }
// 
0x83, 0xc4, 0x1c,                                // 004e8 -  add	 esp, 28			; 0000001cH
0xc3                                             // 004eb -  ret	 0
// ?runDLL@@YAKPAX@Z ENDP					; runDLL

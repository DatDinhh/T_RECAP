#include <cstring>
#include "shared.hpp"
static thread_local std::string error;
#define API extern "C" __declspec(dllexport)
API void* trecap_create(const char*coeff,const char*input){try{pin_native_thread();auto* c=new Context(coeff,input);c->touch();return c;}catch(const std::exception&e){error=e.what();return nullptr;}}
API int trecap_prefault(void*p){try{static_cast<Context*>(p)->touch();return 0;}catch(const std::exception&e){error=e.what();return -1;}}
API int trecap_run(void*p,uint64_t threshold){try{auto*c=static_cast<Context*>(p);c->runner.epoch(c->input,threshold);return 0;}catch(const std::exception&e){error=e.what();return -1;}}
API const int32_t* trecap_y(void*p){return static_cast<Context*>(p)->runner.y.data();}
API uint64_t trecap_y_count(void*){return NY;}
API const uint8_t* trecap_tsp1(void*p){return static_cast<Context*>(p)->runner.wire.data();}
API uint64_t trecap_tsp1_bytes(void*p){return static_cast<Context*>(p)->runner.count;}
API const char* trecap_error(){return error.c_str();}
API void trecap_destroy(void*p){delete static_cast<Context*>(p);}

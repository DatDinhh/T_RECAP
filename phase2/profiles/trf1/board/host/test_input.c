#define main trf1_program_main
#include "trf1_client.c"
#undef main
int main(int argc,char**argv){
 if(argc!=2)return 2;
 uint8_t *data=malloc(MAXPAIRS*2);if(!data)return 2;
 unsigned lengths[]={0,1,2,3,4,191998,192000,192001,192002};
 for(unsigned i=0;i<sizeof lengths/sizeof lengths[0];i++){
   char path[4096];snprintf(path,sizeof path,"%s/input_%u.cu8",argv[1],i);
   FILE*f=fopen(path,"wbx");if(!f)return 2;
   for(unsigned j=0;j<lengths[i];j++)if(fputc((int)(j*73+19)&255,f)==EOF)return 2;
   if(fclose(f))return 2;
   unsigned pairs=0;bool ok=read_input(path,data,&pairs);
   bool expected=lengths[i]>=2&&lengths[i]<=MAXPAIRS*2&&lengths[i]%2==0;
   if(ok!=expected||(ok&&pairs!=lengths[i]/2)){fprintf(stderr,"length%u failed\n",lengths[i]);return 2;}
   if(ok)for(unsigned j=0;j<lengths[i];j++)if(data[j]!=(uint8_t)(j*73+19))return 2;
 }
 unsigned pairs=0;if(read_input(argv[1],data,&pairs))return 2;
 char absent[4096];snprintf(absent,sizeof absent,"%s/absent.cu8",argv[1]);if(read_input(absent,data,&pairs))return 2;
 uint64_t v=0;if(number("-1",3,&v)||number("4",3,&v)||number("1x",3,&v)||!number("3",3,&v)||v!=3)return 2;
 free(data);puts("{\"status\":\"PASS_INPUT_BOUNDARIES\",\"file_cases\":11,\"numeric_cases\":4,\"hardware_access\":false}");return 0;
}

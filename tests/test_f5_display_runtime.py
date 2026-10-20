#!/usr/bin/env python3
"""Independent, portable localization boundary probes.

Run: python tests/test_f5_display_runtime.py --repo .
Requires an already materialized --source (default REPO/_upstream), g++, and git.
Only temporary files are written. This does not substitute for a Windows build.
Can be copied to tests/ and invoked after materialization in CI.
"""
from pathlib import Path
import argparse, importlib.util, json, shutil, subprocess, sys, tempfile

PIN = 'fadc3bf67f6c8548e94914baec3f2e551ba8d8a4'
WRAPPER_SHAPES = r'''
#include "ImGuiLocalization.h"
// Windows/MSVC uses an integer null-pointer constant, not std::nullptr_t.
#undef NULL
#define NULL 0
using namespace OptiScalerCN::UI;
void shapes(){
 bool b=false; int i=0; unsigned int u=0; float f[4]={}; int ints[4]={}; void* ptr=&i;
 const char* a[]={"one","two"}; char buf[64]={}; ImVec2 s(1,2); ImVec4 c(1,2,3,4);
 Begin("Window",NULL,ImGuiWindowFlags_NoSavedSettings);
 Begin("Window");
 Begin("Window",&b,0); Button("Apply",s); SmallButton("Reset"); Checkbox("Option",&b);
 CheckboxFlags("Flags",&u,1u); CheckboxFlags("Flags",&i,1); RadioButton("Radio",true); RadioButton("Radio",&i,1);
 Selectable("Item",b); Selectable("Item",&b,0,s); TreeNode("Node"); TreeNodeEx("Node",0); CollapsingHeader("Header",0);
 CollapsingHeader("Header",&b,0); BeginListBox("Box",s); BeginTabItem("Tab",&b,0); BeginMenu("Menu",true);
 MenuItem("Item","Ctrl+X",false,true); MenuItem("Item","Ctrl+X",&b,true);
 SliderFloat("x",f,0.0f,1.0f,"%.2f",0); SliderFloat2("x",f,0.0f,1.0f); SliderFloat3("x",f,0.0f,1.0f); SliderFloat4("x",f,0.0f,1.0f);
 SliderInt("x",&i,0,1,"%d",0); SliderInt2("x",ints,0,1); SliderInt3("x",ints,0,1); SliderInt4("x",ints,0,1);
 SliderScalar("x",ImGuiDataType_S32,ptr,&i,&i,"%d",0); SliderScalarN("x",ImGuiDataType_S32,ptr,1,&i,&i);
 SliderAngle("x",f,-1.0f,1.0f,"%.2f"); DragFloat("x",f,0.1f); DragFloat2("x",f); DragFloat3("x",f); DragFloat4("x",f);
 DragInt("x",&i); DragInt2("x",ints); DragInt3("x",ints); DragInt4("x",ints); DragScalar("x",ImGuiDataType_S32,ptr);
 InputFloat("x",f); InputFloat2("x",f); InputFloat3("x",f); InputFloat4("x",f); InputInt("x",&i);
 // menu_common.cpp RawFlags and Display/Render Width call shapes.
 InputScalar("##RawFlags",ImGuiDataType_U32,&u,NULL,NULL,"%08X",ImGuiInputTextFlags_CharsHexadecimal);
 InputScalar("Display Width",ImGuiDataType_U32,&u,NULL,NULL,"%u");
 InputScalar("Render Width",ImGuiDataType_U32,&u,NULL,NULL,"%u");
 InputScalar("Default",ImGuiDataType_U32,&u);
 InputScalar("Null format",ImGuiDataType_U32,&u,NULL,NULL,NULL);
 InputScalar("x",ImGuiDataType_S32,ptr,nullptr,nullptr,"%d",0); InputText("x",buf,sizeof buf);
 InputTextMultiline("x",buf,sizeof buf,s); InputTextWithHint("x","hint",buf,sizeof buf);
 ColorEdit3("x",f); ColorEdit4("x",f); TableSetupColumn("x"); TextLink("x"); TextLinkOpenURL("x","https://example.invalid");
 BeginPopupModal("x",&b,0); PlotHistogram("x",f,4); Text("%s %u %d %.2f",buf,u,i,f[0]); TextColored(c,"%s",a[0]);
 LabelText("label","%s",buf); TextDisabled("x"); TextWrapped("x"); BulletText("x"); SetTooltip("x"); SetItemTooltip("x");
 TextUnformatted(buf,buf+3); SeparatorText("x"); BeginCombo("x",a[0]); Combo("x",&i,a,2); Combo("x",&i,"one\0two\0");
 ProgressBar(0.5f,s,"working"); CalcTextSize(buf,buf+3,true); PlotLines("x",f,4,0,"overlay",0.0f,1.0f,s);
 // menu_common.cpp frame-time overlays (full arguments) and plot page (defaults).
 PlotLines("##FrameTimeGraph",[](void* rb,int idx)->float { return static_cast<float*>(rb)[idx]; },f,4,0,nullptr,0.0f,66.6f,s);
 PlotLines("##UpscalerFrameTimeGraph",[](void* rb,int idx)->float { return static_cast<float*>(rb)[idx]; },f,4,0,nullptr,0.0f,20.0f,s);
 PlotLines("Frame time",[](void* rb,int idx)->float { return static_cast<float*>(rb)[idx]; },f,4);
 PlotLines("Upscaler frame time",[](void* rb,int idx)->float { return static_cast<float*>(rb)[idx]; },f,4);
}
'''

def command(args, **kw):
    result = subprocess.run(args, text=True, capture_output=True, **kw)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result.stdout

def extract_hash(text, name):
    start = text.index('ImGuiID ImHashStr(')
    end = text.index('\n}\n', start) + 3
    return text[start:end].replace('ImHashStr(', name+'(', 1)

def run(repo, source):
    compiler = shutil.which('g++')
    if compiler is None:
        raise RuntimeError('g++ unavailable; portable probes have not run')
    path = 'OptiScaler/include/imgui/imgui.cpp'
    upstream = command(['git','-C',str(source),'show',PIN+':'+path])
    patched = (source/path).read_text(encoding='utf-8-sig')
    start = upstream.index('static const ImU32 GCrc32LookupTable[256]')
    end = upstream.index('\n#endif', upstream.index('\n};', start)) + len('\n#endif')
    table = '#ifndef IMGUI_ENABLE_SSE4_2_CRC\n' + upstream[start:end] + '\n'
    sys.path.insert(0, str(repo/'tools'))
    import generate_cpp
    pairs = [
        ('Apply','应用'), ('Reset','重置'), ('Window###fixed','窗口###fixed'),
        ('Model input brightness##','模型输入亮度##'), ('Delete##','删除##'),
        ('Pass {}','第 {} 轮'), ('Off','关闭'),
        ('Could not start: %s','无法启动：%s'),
        ('creating the command allocator','创建命令分配器'),
        ('Value: %s; reason: %s','值：%s；原因：%s'),
        ('creating a shared texture %ux%u format %u','创建共享纹理 %ux%u，格式 %u'),
        ('Item %s (%d)','项目 %s（%d）'),
        ('%d (normal)','%d（常规）'),
        ('more','增加'), ('less','减少'), ('worse','更差'),
        ('{} detail ({:+.0f}%)','细节{}（{:+.0f}%）'),
        ('{} flicker ({:+.0f}%, {})','闪烁{}（{:+.0f}%，{}）'),
        ('{} saturated ({:+.0f} points)','饱和度{}（{:+.0f} 个百分点）'),
    ]
    catalog={'entries':{}}; zh={'entries':{}}
    for i,(a,b) in enumerate(pairs):
        key='fixture.'+str(i)
        catalog['entries'][key]={'source':a,'source_hash':str(i)}
        zh['entries'][key]={'text':b,'source_hash':str(i),'state':'reviewed'}
    with tempfile.TemporaryDirectory(prefix='f5-independent-display-') as temp:
        out=Path(temp); (out/'generated').mkdir()
        (out/'generated/Strings.generated.h').write_text(generate_cpp.render_header(catalog,zh),encoding='ascii')
        overlay=repo/'overlay/OptiScaler/localization'
        shutil.copy2(overlay/'RuntimeText.h',out/'RuntimeText.h')
        wrapper=(overlay/'ImGuiLocalization.h').read_text()
        wrapper=wrapper.replace('#include "Localization.h"', '#include "imgui.h"\n#include <filesystem>\nnamespace OptiScalerCN::Loc { inline bool active=true; inline bool IsChineseActive(){ return active; } }')
        (out/'ImGuiLocalization.h').write_text(wrapper)
        cpp = r'''
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include <iostream>
#include "ImGuiLocalization.h"
#undef NULL
#define NULL 0
static std::string captured, capturedLabel, capturedPreview;
static std::vector<std::string> capturedItems;
static float capturedExtra=0;
static ImGuiID capturedId=0;
static bool* capturedOpen=nullptr;
static int capturedFlags=0;
static ImGuiDataType capturedType=0;
static void* capturedData=nullptr;
static const void* capturedStep=nullptr;
static const void* capturedFastStep=nullptr;
static float (*capturedGetter)(void*,int)=nullptr;
static const float* capturedValues=nullptr;
static int capturedCount=0,capturedOffset=0,capturedStride=0;
static bool capturedOverlayNull=false;
static float capturedLow=0,capturedHigh=0,capturedSample=0;
static ImVec2 capturedSize;
namespace ImGui {
bool Begin(const char* label,bool* open,ImGuiWindowFlags flags) {
 capturedLabel=label;capturedOpen=open;capturedFlags=flags;
 if(open)*open=false;return true;
}
bool InputScalar(const char* label,ImGuiDataType type,void* data,const void* step,const void* fast,const char* format,ImGuiInputTextFlags flags) {
 capturedLabel=label;capturedType=type;capturedData=data;capturedStep=step;capturedFastStep=fast;
 captured=format?format:"<null>";capturedFlags=flags;
 if(type==ImGuiDataType_U32)*static_cast<unsigned int*>(data)+=1;
 return true;
}
void PlotLines(const char* label,float(*getter)(void*,int),void* data,int count,int offset,const char* overlay,float low,float high,ImVec2 size) {
 capturedLabel=label;capturedGetter=getter;capturedData=data;capturedCount=count;capturedOffset=offset;
 capturedOverlayNull=overlay==nullptr;captured=overlay?overlay:"";capturedLow=low;capturedHigh=high;capturedSize=size;
 capturedSample=getter(data,1);
}
void PlotLines(const char* label,const float* values,int count,int offset,const char* overlay,float low,float high,ImVec2 size,int stride) {
 capturedLabel=label;capturedValues=values;capturedCount=count;capturedOffset=offset;capturedStride=stride;
 capturedOverlayNull=overlay==nullptr;captured=overlay?overlay:"";capturedLow=low;capturedHigh=high;capturedSize=size;
}
} // namespace ImGui
struct PlotData { float samples[3]; int calls=0; int lastIndex=-1; };
static float PlotGetter(void* data,int index) {
 auto* plot=static_cast<PlotData*>(data);++plot->calls;plot->lastIndex=index;return plot->samples[index];
}
namespace ImGui {
void Text(const char* format, ...) {
 char buffer[4096]; va_list args; va_start(args,format);
 std::vsnprintf(buffer,sizeof buffer,format,args); va_end(args); captured=buffer;
}
bool InputText(const char* label,char* buffer,size_t size,ImGuiInputTextFlags,ImGuiInputTextCallback,void*) {
 capturedLabel=label; if(size>8) std::strcpy(buffer,"Edited%"); return true;
}
bool SliderInt(const char* label,int* value,int low,int high,const char* format,ImGuiSliderFlags) {
 capturedLabel=label; captured=format; *value=high; return true;
}
bool Combo(const char* label,int* current,const char* const items[],int count,int) {
 capturedLabel=label; capturedItems.assign(items,items+count); *current=count-1; return true;
}
bool BeginCombo(const char* label,const char* preview,ImGuiComboFlags) {
 capturedLabel=label; capturedPreview=preview?preview:""; return false;
}
bool Selectable(const char* label,bool,ImGuiSelectableFlags,const ImVec2&) {
 capturedLabel=label; return false;
}
void SeparatorTextEx(ImGuiID id,const char* begin,const char* end,float extra) {
 captured.assign(begin,end); capturedExtra=extra; capturedId=id;
}
void TextUnformatted(const char* begin,const char* end) { captured=end?std::string(begin,end):std::string(begin); }
}
'''+table+extract_hash(upstream,'UpstreamHash')+extract_hash(patched,'PatchedHash')+r'''
int main(){
 unsigned tests=0, failed=0;
 auto check=[&](bool ok,const char* description){++tests;if(!ok){++failed;std::cout<<"FAIL "<<description<<"\n";}};
 for(ImGuiID seed:{0u,0x12345678u,0xffffffffu,3950358u})
 for(const std::string original:{"Apply","Reset##brightness","Window###fixed","Pass 4","##hidden","A###id###last",""}){
   auto translated=OptiScalerCN::Runtime::Label(original,"中文");
   for(bool sized:{false,true}){
     auto expected=UpstreamHash(original.c_str(),sized?original.size():0,seed);
     check(expected==PatchedHash(translated.c_str(),sized?translated.size():0,seed),"translated ID equal to upstream ID");
     check(expected==PatchedHash(original.c_str(),sized?original.size():0,seed),"unmodified upstream ID equal");
   }
 }
 const std::string marker="中文###\037CNID\037", sliced=marker+"do not read beyond slice";
 check(PatchedHash(sliced.data(),marker.size(),123)==UpstreamHash("",0,123),"marker-only explicit slice is empty, not a NUL tail");
 check(OptiScalerCN::UI::LabelValue("Model input brightness##trimfoo").find("模型输入亮度")==0,"dynamic ## visible prefix translated");
 check(OptiScalerCN::UI::LabelValue("Reset##Skin colour").find("重置")==0,"composed reset translated");
 check(OptiScalerCN::UI::LabelValue("Delete##trimfoo2").find("删除")==0,"dynamic row delete translated");
 auto pass=OptiScalerCN::UI::LabelValue("Pass 4");
 check(pass.find("第 4 轮")==0,"formatted pass label translated");
 check(OptiScalerCN::Runtime::Translate("Item A (B) (3)")=="项目 A (B)（3）","delimiter inside string capture backtracks");
 check(OptiScalerCN::Runtime::Translate("Could not start: creating a shared texture 1920x1080 format 7")=="无法启动：创建共享纹理 1920x1080，格式 7","nested format capture translated");
 OptiScalerCN::UI::Text("Value: %s; reason: %s","100% {literal}","text %n {0}##id");
 check(captured=="值：100% {literal}；原因：text %n {0}##id","captured percent and braces never reparsed");
 OptiScalerCN::UI::Text("Could not start: %s","creating the command allocator");
 check(captured=="无法启动：创建命令分配器","typed formatting translates safe phrase argument");

 OptiScalerCN::UI::Text("Value: %s; reason: %s",OptiScalerCN::UI::Raw("Off"),OptiScalerCN::UI::Raw("Value: %n; reason: {bad}"));
 check(captured=="值：Off；原因：Value: %n; reason: {bad}","raw data matches catalog but is never translated or reparsed");
 check(OptiScalerCN::UI::LabelValue("Unknown##technical")=="Unknown##technical","unknown visible prefix keeps complete original bytes");
 char edited[64]="Off";
 check(OptiScalerCN::UI::InputText("Apply",edited,sizeof edited),"input return value forwarded");
 check(std::string(edited)=="Edited%","mutable InputText buffer reaches original API");
 check(PatchedHash(capturedLabel.c_str(),0,777)==UpstreamHash("Apply",0,777),"input label source ID preserved");
 int number=0;
 check(OptiScalerCN::UI::SliderInt("Apply",&number,0,4,"%d (normal)"),"numeric return value forwarded");
 check(number==4 && captured=="%d（常规）","numeric pointer and translated display format preserved");
 const char* items[]={"Off","Apply"}; int current=0;
 check(OptiScalerCN::UI::Combo("Apply",&current,items,2),"combo return value forwarded");
 check(current==1 && std::string(items[0])=="Off" && std::string(items[1])=="Apply","combo selection changes index not original array");
 for(int i=0;i<2;++i)
   check(PatchedHash(capturedItems[i].c_str(),0,888)==UpstreamHash(items[i],0,888),"combo item ID preserves original under popup scope");
 OptiScalerCN::UI::BeginComboRawPreview("Apply","Off");
 check(capturedPreview=="Off","raw filename preview not translated");
 check(PatchedHash(capturedLabel.c_str(),0,999)==UpstreamHash("Apply",0,999),"raw preview combo label translated with source ID");
 OptiScalerCN::UI::SelectableRaw("Off");
 check(capturedLabel=="Off","raw filename selectable not translated");
 const char slice[]="Apply ignored";
 OptiScalerCN::UI::SeparatorTextEx(54,slice,slice+5,13.5f);
 check(captured=="应用" && capturedExtra==13.5f && capturedId==54,"separator text slice translated and non-text parameters retained");
 OptiScalerCN::UI::TextUnformatted(slice,slice+5);
 check(captured=="应用","unformatted slice has no trailing data or format parsing");

 // Keep MSVC NULL=0 at the call boundary: forwarding an int variable is not a null-pointer constant.
 check(OptiScalerCN::UI::Begin("Apply",NULL,ImGuiWindowFlags_NoSavedSettings),"Begin NULL return forwarded");
 check(capturedOpen==nullptr && capturedFlags==ImGuiWindowFlags_NoSavedSettings,"Begin NULL and flags forwarded");
 check(PatchedHash(capturedLabel.c_str(),0,1001)==UpstreamHash("Apply",0,1001),"Begin NULL source ID preserved");
 OptiScalerCN::UI::Begin("Apply");
 check(capturedOpen==nullptr && capturedFlags==0,"Begin omitted defaults preserved");
 bool open=true;
 check(OptiScalerCN::UI::Begin("Apply",&open,ImGuiWindowFlags_NoResize),"Begin pointer return forwarded");
 check(capturedOpen==&open && !open && capturedFlags==ImGuiWindowFlags_NoResize,"Begin non-null open pointer preserved");
 unsigned int scalar=0x3f;
 check(OptiScalerCN::UI::InputScalar("##RawFlags",ImGuiDataType_U32,&scalar,NULL,NULL,"%08X",ImGuiInputTextFlags_CharsHexadecimal),"InputScalar NULL return forwarded");
 check(capturedType==ImGuiDataType_U32 && capturedData==&scalar && scalar==0x40,"InputScalar data pointer and type preserved");
 check(capturedStep==nullptr && capturedFastStep==nullptr && captured=="%08X" && capturedFlags==ImGuiInputTextFlags_CharsHexadecimal,"InputScalar NULL steps format and flags forwarded");
 check(PatchedHash(capturedLabel.c_str(),0,1002)==UpstreamHash("##RawFlags",0,1002),"InputScalar hidden source ID preserved");
 OptiScalerCN::UI::InputScalar("Display Width",ImGuiDataType_U32,&scalar,NULL,NULL,"%u");
 check(capturedData==&scalar && capturedStep==nullptr && capturedFastStep==nullptr && captured=="%u" && capturedFlags==0,"InputScalar Width default flags preserved");
 OptiScalerCN::UI::InputScalar("Apply",ImGuiDataType_U32,&scalar);
 check(capturedData==&scalar && capturedStep==nullptr && capturedFastStep==nullptr && captured=="<null>" && capturedFlags==0,"InputScalar all omitted defaults preserved");
 OptiScalerCN::UI::InputScalar("Apply",ImGuiDataType_U32,&scalar,NULL,NULL,NULL);
 check(capturedStep==nullptr && capturedFastStep==nullptr && captured=="<null>","InputScalar explicit integer NULL display format preserved");
 unsigned int step=1,fastStep=10;
 OptiScalerCN::UI::InputScalar("Apply",ImGuiDataType_U32,&scalar,&step,&fastStep,"%d (normal)",ImGuiInputTextFlags_EnterReturnsTrue);
 check(capturedStep==&step && capturedFastStep==&fastStep && captured=="%d（常规）" && capturedFlags==ImGuiInputTextFlags_EnterReturnsTrue,"InputScalar non-null steps and translated format preserved");
 PlotData plot{{11.0f,22.0f,33.0f}};
 OptiScalerCN::UI::PlotLines("Apply",PlotGetter,&plot,3,2,"Off",-5.0f,66.6f,ImVec2(90,45));
 check(capturedGetter==PlotGetter && capturedData==&plot,"PlotLines callback and opaque data identity preserved");
 check(plot.calls==1 && plot.lastIndex==1 && capturedSample==22.0f,"PlotLines invokes original callback with original data and index");
 check(capturedCount==3 && capturedOffset==2 && capturedLow==-5.0f && capturedHigh==66.6f && capturedSize.x==90 && capturedSize.y==45,"PlotLines callback graph numeric parameters preserved");
 check(captured=="关闭" && !capturedOverlayNull,"PlotLines callback overlay translated");
 check(PatchedHash(capturedLabel.c_str(),0,1003)==UpstreamHash("Apply",0,1003),"PlotLines callback source ID preserved");
 OptiScalerCN::UI::PlotLines("##FrameTimeGraph",PlotGetter,&plot,3,0,nullptr,0.0f,66.6f,ImVec2(80,30));
 check(capturedOverlayNull && capturedGetter==PlotGetter && capturedData==&plot && capturedHigh==66.6f,"PlotLines real overlay null call shape preserved");
 OptiScalerCN::UI::PlotLines("Apply",PlotGetter,&plot,3);
 check(capturedOverlayNull && capturedOffset==0 && capturedLow==FLT_MAX && capturedHigh==FLT_MAX && capturedSize.x==0 && capturedSize.y==0,"PlotLines callback omitted defaults preserved");
 float interleaved[]={1.0f,99.0f,2.0f,99.0f};
 OptiScalerCN::UI::PlotLines("Apply",interleaved,2,1,"Off",0.0f,3.0f,ImVec2(60,20),2*sizeof(float));
 check(capturedValues==interleaved && capturedStride==2*sizeof(float) && capturedCount==2 && capturedOffset==1,"PlotLines array pointer stride count and offset preserved");
 check(captured=="关闭" && capturedLow==0.0f && capturedHigh==3.0f && capturedSize.x==60 && capturedSize.y==20,"PlotLines array overlay and graph parameters preserved");
 OptiScalerCN::UI::PlotLines("Band-pass##tune",interleaved,2,0,nullptr,FLT_MAX,FLT_MAX,ImVec2(0,50));
 check(capturedValues==interleaved && capturedStride==sizeof(float) && capturedOverlayNull && capturedSize.y==50,"PlotLines real calibration array call shape preserved");

 check(OptiScalerCN::UI::ComparisonValue("more detail (+20%), more flicker (+10%, worse), less saturated (-5 points)")=="细节增加（+20%）；闪烁增加（+10%，更差）；饱和度减少（-5 个百分点）","comparison clauses translated without greedy reordering or splitting inner comma");
 check(OptiScalerCN::UI::PathUtf8(std::filesystem::u8path("路径/中文 Off.cube"))=="路径/中文 Off.cube","UTF-8 display path retains unicode and raw filename bytes");
 OptiScalerCN::Loc::active=false;
 check(OptiScalerCN::UI::ComparisonValue("more detail (+20%), more flicker (+10%, worse)")=="more detail (+20%), more flicker (+10%, worse)","comparison English fallback keeps exact original bytes");
 check(OptiScalerCN::UI::LabelValue("Apply")=="Apply","English fallback has original label");
 check(OptiScalerCN::UI::LabelValue("Reset##x")=="Reset##x","English fallback keeps hidden-suffix original bytes");
 check(OptiScalerCN::UI::LabelValue("Window###fixed")=="Window###fixed","English fallback keeps explicit-ID original bytes");
 OptiScalerCN::UI::Text("Value: %s; reason: %s","Off","literal %n");
 check(captured=="Value: Off; reason: literal %n","English fallback preserves format and values");
 std::cout<<"portable boundary assertions="<<tests<<" failures="<<failed<<"\n";
 return failed?1:0;
}
'''
        (out/'wrapper-shapes.cpp').write_text(WRAPPER_SHAPES)
        command([compiler,'-std=c++17','-I',str(out),'-I',str(source/'OptiScaler/include/imgui'),'-I',str(source/'OptiScaler/include'),'-fsyntax-only',str(out/'wrapper-shapes.cpp')])
        print('wrapper overload syntax checks passed')
        (out/'probe.cpp').write_text(cpp)
        executable=out/'probe'
        command([compiler,'-std=c++17','-O1','-I',str(out),'-I',str(source/'OptiScaler/include/imgui'),'-I',str(source/'OptiScaler/include'),str(out/'probe.cpp'),'-o',str(executable)])
        result=subprocess.run([str(executable)],text=True,capture_output=True)
        print(result.stdout,end=''); print(result.stderr,end='',file=sys.stderr)
        return result.returncode

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--source',type=Path)
    args=parser.parse_args();repo=args.repo.resolve();source=(args.source or repo/'_upstream').resolve()
    return run(repo,source)
if __name__=='__main__': raise SystemExit(main())

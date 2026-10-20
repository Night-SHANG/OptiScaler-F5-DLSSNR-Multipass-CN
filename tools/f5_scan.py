"""F5-specific catalog-only coverage. No producer literal is rewritten."""
from loclib import Candidate, _string_literals_in_region, mask_cpp, find_matching, should_exclude, extract_string_expression
import re, fnmatch

# Files whose string constants are display data or transitive display producers.
# Technical values are cataloged only when also useful as displayed words;
# runtime lookup never changes their original storage or comparison semantics.
DISPLAY_FILES = [
 'OptiScaler/menu/menu_common.cpp', 'OptiScaler/dlssnr/DlssNr_Menu.cpp',
 'OptiScaler/native/NativeDriver*.cpp', 'OptiScaler/resource_tracking/GenericDepth_*.cpp',
 'OptiScaler/shaders/dlssnr/DlssNr_Late.inl', 'OptiScaler/shaders/dlssnr/DlssNr_DeferredSr.inl',
 'OptiScaler/dlssnr/DlssNr_LutFile.h',
]
FUNCTIONS = {
 'OptiScaler/motion/MotionProfiles.h': ['ProfileMenuName'],
 'OptiScaler/native/NativeLowLatencyRule.h': ['OutputAvailability','StatusLabel','ActiveInputText','DecisionText'],
 'OptiScaler/native/NativeLowLatency.h': ['ReasonText'],
 'OptiScaler/native/NativeLowLatency.cpp': ['PathText','OutputText','CapText'],
 'OptiScaler/shaders/dlssnr/DlssNr_ColourEncoding.h': ['Name','Resolve','ResolveFinished','MismatchWarning','Describe'],
 'OptiScaler/dlssnr/DlssNr_ColourEncodingStatus.cpp': ['ReadColourEncodingStatus'],
 'OptiScaler/shaders/dlssnr/DlssNr_ExposureCalibrate.h': ['AbortText','BlockerText'],
 'OptiScaler/shaders/dlssnr/DlssNr_ExposureCalibrate_Run.h': ['StopText','DetailWords','FlickerWords','ColourWords','ShadowWords','CompareWords'],
 'OptiScaler/include/imgui/ImGuiNotify.hpp': ['getDefaultTitle'],
 'OptiScaler/dlssnr/DlssNrVitReuse.h': ['CheckOutput','Status'],
 'OptiScaler/dlssnr/DlssNrNative.cpp': ['VitCopyRecord'],
 'OptiScaler/dlssnr/DlssNrDetailReuse.h': ['UnavailableOnRoute'],
 'OptiScaler/dlssnr/DlssNrEditCache.h': ['StandAsideReason'],
 'OptiScaler/dlssnr/DlssNrDetailReuseHost.h': ['FrameGenerationInUse'],
 'OptiScaler/framegen/dlssg/MfgUnlockFlip.h': ['Describe'],
}
# Immutable struct tables: only human-facing string columns, not stable name keys.
TABLES = {
 'OptiScaler/menu/MenuPages.h': [('kPages', [1])],
 'OptiScaler/dlssnr/DlssNr_LookPresets.h': [('kLooks', [0,1])],
 'OptiScaler/shaders/dlssnr/DlssNr_Spatial.h': [('kNamedLayouts', [0])],
}
PRODUCER_FILES = [
 'OptiScaler/dlssnr/DlssNr_ExposureScan.cpp', 'OptiScaler/shaders/dlssnr/DlssNr_Dx12.cpp',
 'OptiScaler/dlssnr/DlssNrFeature_Vk.cpp', 'OptiScaler/dlssnr/DlssNrDetailReuseHost.h',
 'OptiScaler/shaders/dlssnr/DlssNr_EditCache.inl', 'OptiScaler/dlssnr/DlssNrVitReuse.h',
 'OptiScaler/dlssnr/DlssNrNative.cpp', 'OptiScaler/dlssnr/DlssNrHybridBuilder.h', 'OptiScaler/dlssnr/forwarder/dlssnr_forwarder.cpp', 'OptiScaler/native/NativeProducer.cpp',
 'OptiScaler/native/VirtualUpscalerDriver.cpp', 'OptiScaler/native/VkPresentBridge*.cpp',
 'OptiScaler/native/VkFrameSource.cpp', 'OptiScaler/motion/*.cpp',
 'OptiScaler/framegen/dlssg/MfgUnlock*.h', 'OptiScaler/framegen/dlssg/MfgUnlock.cpp',
 'OptiScaler/framegen/dlssg/AmpereMfgLoader.cpp',
]

def literals(text, rel, start, end, tag, rules):
    found = list(_string_literals_in_region(text,start,end)); merged=[]
    for left,right,source,expr in found:
        if merged and not text[merged[-1][1]:left].strip():
            a,b,s,e=merged.pop(); merged.append((a,right,s+source,text[a:right]))
        else: merged.append((left,right,source,expr))
    out=[]
    for left,right,source,expr in merged:
        if should_exclude(source,rules): continue
        out.append(Candidate(rel,tag,0,source,left,right,text.count('\n',0,left)+1,expr,False))
    return out

def find_f5_candidates(text, rel, rules):
    result=[]; masked=mask_cpp(text)
    if any(fnmatch.fnmatch(rel,p) for p in DISPLAY_FILES):
        for c in literals(text,rel,0,len(text),'f5:display-data',rules):
            # Headers, logs and diagnostic-only calls do not enter display inventory.
            line_start=text.rfind('\n',0,c.start)+1
            context=text[max(0,line_start-250):c.start]
            if re.search(r'#\s*include\s*$',text[line_start:c.start]): continue
            if re.search(r'\b(?:LOG_\w+|printf|OutputDebugString\w*)\s*\([^;{}]*$',context): continue
            result.append(c)
    for name in FUNCTIONS.get(rel,[]):
        for m in re.finditer(r'\b'+re.escape(name)+r'\s*\(',masked):
            p=masked.find('(',m.start());q=find_matching(text,p)
            if q<0: continue
            b=masked.find('{',q);semi=masked.find(';',q)
            if b<0 or (semi>=0 and semi<b): continue
            e=find_matching(text,b,'{','}')
            if e>=0: result+=literals(text,rel,b+1,e,'f5:return:'+name,rules)
    for table,columns in TABLES.get(rel,[]):
        m=re.search(r'\b'+table+r'\s*\[\s*\d*\s*\]\s*=\s*\{',masked)
        if not m: continue
        b=masked.find('{',m.start());end=find_matching(text,b,'{','}')
        if end<0: continue
        for row in re.finditer(r'\{',masked[b+1:end]):
            rb=b+1+row.start();re_=find_matching(text,rb,'{','}')
            tokens=literals(text,rel,rb+1,re_,'f5:table:'+table,rules)
            # Column indexes refer to string columns; enum and numeric values stay outside the list.
            result.extend(c for index,c in enumerate(tokens) if index in columns)
    if any(fnmatch.fnmatch(rel,p) for p in PRODUCER_FILES):
        # Only status/error assignments and reason-producing calls, never generic logging or code strings.
        names=r'(?:_error|_why|_refusal|g_refusal|reason|modelError|status|standsAside|ErrorMessage|TemporalDetail|FlipMetering|why|detail|whyNot|kBelowMinimumFps|kEdgeCompression|err|g_modelError)'
        for m in re.finditer(r'\b'+names+r'\s*=(?!=)',masked):
            semi=masked.find(';',m.end())
            if semi>=0: result+=literals(text,rel,m.end(),semi,'f5:status-assignment',rules)
        for m in re.finditer(r'\b(?:Fail|Disable|Say|ReportLutStatus|SetStatus|SetError|GiveUpOutput|runtime_error|recordModelError)\s*\(',masked):
            p=masked.find('(',m.start());q=find_matching(text,p)
            if q>=0: result+=literals(text,rel,p+1,q,'f5:status-call',rules)
    # Aggregate initializer syntax is the dominant notification constructor form.
    for m in re.finditer(r'\bImGui::InsertNotification\s*\(',masked):
        p=masked.find('(',m.start());q=find_matching(text,p)
        if q>=0: result+=literals(text,rel,p+1,q,'f5:toast-insert',rules)
    # Toast constructor content is user-visible even when outside menu files.
    for m in re.finditer(r'\bImGuiToast\s*(?:\w+\s*)?[({]',masked):
        p=next((i for i in range(m.start(),m.end()) if masked[i] in '({'),-1)
        if p<0: continue
        q=find_matching(text,p,masked[p],')' if masked[p]=='(' else '}')
        if q>=0: result+=literals(text,rel,p+1,q,'f5:toast-constructor',rules)
    # Assignment-built notification messages are read at the final toast boundary.
    for m in re.finditer(r'\b(?:toastMsg|message|warningText|untilRestart|pointNote|runSuffix|presetHelp|spoofingText|disabledReason)\s*(?:\+?=)',masked):
        semi=masked.find(';',m.end())
        if semi>=0 and (rel in DISPLAY_FILES or 'toastMsg' in masked[m.start():m.end()]):
            result+=literals(text,rel,m.end(),semi,'f5:ui-assignment',rules)
    return result

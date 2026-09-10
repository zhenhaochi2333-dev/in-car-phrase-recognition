#include "core.h"
#include "generated/weights.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <complex>
#include <exception>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr int samples = 16000, win = 480, hop = 160, nfft = 512, mels = 40, frames = 101;
constexpr double pi = 3.14159265358979323846;
thread_local std::string last_error;

struct Tensor {
    int c, h, w;
    std::vector<double> data;
    Tensor(int channels, int height, int width)
        : c(channels), h(height), w(width), data(size_t(c)*h*w, 0.0) {}
    double& at(int ch, int f, int t) { return data[(size_t(ch)*h+f)*w+t]; }
    double at(int ch, int f, int t) const { return data[(size_t(ch)*h+f)*w+t]; }
    double padded(int ch, int f, int t) const {
        return f<0 || f>=h || t<0 || t>=w ? 0.0 : at(ch,f,t);
    }
};

void fft(std::array<std::complex<double>, nfft>& a) {
    for (int i=1,j=0; i<nfft; ++i) {
        int bit=nfft>>1;
        for (; j&bit; bit>>=1) j^=bit;
        j^=bit;
        if (i<j) std::swap(a[i],a[j]);
    }
    for (int len=2; len<=nfft; len<<=1) {
        const auto root=std::polar(1.0,-2.0*pi/len);
        for (int i=0; i<nfft; i+=len) {
            std::complex<double> z(1.0,0.0);
            for (int j=0; j<len/2; ++j) {
                auto u=a[i+j],v=a[i+j+len/2]*z;
                a[i+j]=u+v; a[i+j+len/2]=u-v; z*=root;
            }
        }
    }
}

struct Context {
    std::array<double,win> window{};
    std::array<double,257*mels> bank{};
    Context() {
        for(int i=0;i<win;++i) window[i]=0.5*(1-std::cos(2*pi*i/win));
        std::array<double,mels+2> f{};
        const double maxmel=2595*std::log10(1+8000.0/700);
        for(int i=0;i<mels+2;++i) f[i]=700*(std::pow(10,maxmel*i/(mels+1)/2595)-1);
        for(int k=0;k<257;++k) {
            const double hz=k*16000.0/nfft;
            for(int m=0;m<mels;++m)
                bank[k*mels+m]=std::max(0.0,std::min((hz-f[m])/(f[m+1]-f[m]),
                                                     (f[m+2]-hz)/(f[m+2]-f[m+1])));
        }
    }
    Tensor features(const float* pcm) const {
        Tensor out(1,mels,frames);
        for(int t=0;t<frames;++t) {
            std::array<std::complex<double>,nfft> a{};
            for(int i=0;i<win;++i) {
                int index=t*hop+i-win/2;
                if(index<0) index=-index;
                if(index>=samples) index=2*samples-2-index;
                a[i]=static_cast<double>(pcm[index])*window[i];
            }
            fft(a);
            for(int m=0;m<mels;++m) {
                double sum=0;
                for(int k=0;k<257;++k) sum+=std::norm(a[k])*bank[k*mels+m];
                out.at(0,m,t)=std::log(sum+1e-6);
            }
        }
        return out;
    }
};

double bn(double value,int channel,int weight,int norm) {
    return (value-course::running_means[norm][channel]) /
        std::sqrt(course::running_vars[norm][channel]+1e-5) *
        course::weights[weight][channel]+course::biass[norm][channel];
}

Tensor entry(const Tensor& input) {
    Tensor out(16,20,input.w);
    for(int c=0;c<16;++c) for(int f=0;f<20;++f) for(int t=0;t<input.w;++t) {
        double sum=0;
        for(int kf=0;kf<5;++kf) for(int kt=0;kt<5;++kt)
            sum+=input.padded(0,2*f+kf-2,t+kt-2)*course::weights[0][c*25+kf*5+kt];
        out.at(c,f,t)=std::max(0.0,bn(sum,c,1,0));
    }
    return out;
}

Tensor block(const Tensor& input,int channels,int stride,int dilation,
             bool transition,int& weight,int& norm) {
    Tensor projected= input;
    if(transition) {
        projected=Tensor(channels,input.h,input.w);
        for(int c=0;c<channels;++c) for(int f=0;f<input.h;++f) for(int t=0;t<input.w;++t) {
            double sum=0;
            for(int ci=0;ci<input.c;++ci)
                sum+=input.at(ci,f,t)*course::weights[weight][c*input.c+ci];
            projected.at(c,f,t)=std::max(0.0,bn(sum,c,weight+1,norm));
        }
        weight+=2; ++norm;
    }
    const int height=(projected.h-1)/stride+1;
    Tensor freq(channels,height,input.w);
    // Course arrays are oversized [C][C][3][1]; each channel's taps are in [c][0].
    for(int c=0;c<channels;++c) for(int f=0;f<height;++f) for(int t=0;t<input.w;++t) {
        double sum=0;
        for(int k=0;k<3;++k)
            sum+=projected.padded(c,f*stride+k-1,t)*course::weights[weight][c*channels*3+k];
        const int group=c*5+f/(height/5);
        freq.at(c,f,t)=bn(sum,group,weight+1,norm);
    }
    weight+=2; ++norm;
    Tensor temporal(channels,1,input.w), average(channels,1,input.w);
    for(int c=0;c<channels;++c) for(int t=0;t<input.w;++t) {
        for(int f=0;f<height;++f) average.at(c,0,t)+=freq.at(c,f,t)/height;
    }
    for(int c=0;c<channels;++c) for(int t=0;t<input.w;++t) {
        double sum=0;
        for(int k=0;k<3;++k)
            sum+=average.padded(c,0,t+(k-1)*dilation)*course::weights[weight][c*channels*3+k];
        sum=bn(sum,c,weight+1,norm);
        temporal.at(c,0,t)=sum>=0 ? sum/(1+std::exp(-sum)) : sum*std::exp(sum)/(1+std::exp(sum));
    }
    weight+=2; ++norm;
    Tensor out(channels,height,input.w);
    for(int c=0;c<channels;++c) for(int t=0;t<input.w;++t) {
        double sum=0;
        for(int ci=0;ci<channels;++ci) sum+=temporal.at(ci,0,t)*course::weights[weight][c*channels+ci];
        for(int f=0;f<height;++f)
            out.at(c,f,t)=std::max(0.0,sum+freq.at(c,f,t)+(transition?0.0:input.at(c,f,t)));
    }
    ++weight;
    return out;
}

void predict(Context& ctx,const float* pcm,double* logits,double* scores) {
    Tensor x=entry(ctx.features(pcm));
    constexpr int channels[]={8,12,16,20}, counts[]={2,2,4,4}, dilations[]={1,2,4,8};
    int weight=2,norm=1;
    for(int stage=0;stage<4;++stage) for(int b=0;b<counts[stage];++b)
        x=block(x,channels[stage],b==0 && (stage==1 || stage==2)?2:1,
                dilations[stage],b==0,weight,norm);
    if(weight!=70 || norm!=29) throw std::runtime_error("Parameter layout mismatch");
    Tensor y(20,1,x.w);
    for(int c=0;c<20;++c) for(int t=0;t<x.w;++t) {
        double sum=0;
        for(int f=0;f<5;++f) for(int k=0;k<5;++k)
            sum+=x.padded(c,f,t+k-2)*course::weights[70][c*20*25+f*5+k];
        y.at(c,0,t)=sum;
    }
    std::array<double,32> pooled{};
    for(int c=0;c<32;++c) for(int t=0;t<x.w;++t) {
        double sum=0;
        for(int ci=0;ci<20;++ci) sum+=y.at(ci,0,t)*course::weights[71][c*20+ci];
        pooled[c]+=std::max(0.0,bn(sum,c,72,29))/x.w;
    }
    for(int c=0;c<12;++c) {
        logits[c]=course::biass[30][c];
        for(int ci=0;ci<32;++ci) logits[c]+=pooled[ci]*course::weights[73][c*32+ci];
        if(!std::isfinite(logits[c])) throw std::runtime_error("Non-finite network output");
    }
    const double peak=*std::max_element(logits,logits+12);
    double denom=0;
    for(int c=0;c<12;++c) { scores[c]=std::exp(logits[c]-peak); denom+=scores[c]; }
    for(int c=0;c<12;++c) scores[c]/=denom;
}

void validate(void* handle,const float* pcm,int length) {
    if(!handle || !pcm || length!=samples) throw std::invalid_argument("Expected handle and 16000 PCM samples");
    for(int i=0;i<length;++i) if(!std::isfinite(pcm[i]) || std::abs(pcm[i])>1.01f)
        throw std::invalid_argument("PCM must be finite and normalized to [-1,1]");
}
}

void* lab_create(void) {
    try { last_error.clear(); return new Context(); }
    catch(const std::exception& e) { last_error=e.what(); return nullptr; }
}
void lab_destroy(void* handle) { delete static_cast<Context*>(handle); }
const char* lab_last_error(void) { return last_error.c_str(); }
int lab_predict(void* handle,const float* pcm,int length,double* logits,double* scores) {
    try {
        validate(handle,pcm,length);
        if(!logits || !scores) throw std::invalid_argument("Missing output arrays");
        predict(*static_cast<Context*>(handle),pcm,logits,scores);
        last_error.clear(); return 0;
    } catch(const std::exception& e) { last_error=e.what(); return -1; }
}
int lab_features(void* handle,const float* pcm,int length,double* output) {
    try {
        validate(handle,pcm,length);
        if(!output) throw std::invalid_argument("Missing output array");
        auto x=static_cast<Context*>(handle)->features(pcm);
        std::copy(x.data.begin(),x.data.end(),output);
        last_error.clear(); return 0;
    } catch(const std::exception& e) { last_error=e.what(); return -1; }
}

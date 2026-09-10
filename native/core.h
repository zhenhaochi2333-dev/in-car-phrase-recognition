#pragma once
#ifdef _WIN32
#define LAB_API __declspec(dllexport)
#else
#define LAB_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
LAB_API void* lab_create(void);
LAB_API void lab_destroy(void* handle);
// input: 16000 finite float PCM samples in [-1,1]. Output arrays: length 12.
LAB_API int lab_predict(void* handle, const float* pcm, int length,
                        double* logits, double* scores);
// Optional diagnostic feature export, 40*101 doubles in frequency/time order.
LAB_API int lab_features(void* handle, const float* pcm, int length, double* output);
LAB_API const char* lab_last_error(void);
#ifdef __cplusplus
}
#endif

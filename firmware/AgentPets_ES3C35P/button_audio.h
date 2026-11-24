#pragma once
#include <stdint.h>

bool buttonAudioBegin(bool muted, uint8_t volume);
void buttonAudioMute(bool muted);
void buttonAudioSetVolume(uint8_t volume);
uint8_t buttonAudioVolume();
void buttonAudioReport();
void buttonAudioPlay();
bool buttonAudioReady();
bool buttonAudioMuted();

enum class PetVoice : uint8_t { Approval, Question, Failure, Ready, Working };
void buttonAudioVoice(bool enabled);
bool buttonAudioVoiceEnabled();
void buttonAudioSpeak(PetVoice phrase);

void buttonAudioPreviewMute(bool enabled);

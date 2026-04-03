import { useState, useRef, useEffect } from "react";
import { MdMic, MdStop, MdAutorenew } from "react-icons/md";
import type { STTParseResult } from "@/types";

interface SpeechRecognitionEvent {
  results: {
    [index: number]: { [index: number]: { transcript: string } };
    length: number;
  };
  resultIndex: number;
}

interface Props {
  onParsed: (result: STTParseResult) => void;
  parseSTT: (rawText: string) => Promise<STTParseResult | null>;
}

type Status = "idle" | "recording" | "processing";

export default function STTInput({ onParsed, parseSTT }: Props) {
  const [status, setStatus] = useState<Status>("idle");
  const [transcript, setTranscript] = useState("");
  const [supported, setSupported] = useState(true);
  const recognitionRef = useRef<ReturnType<typeof createRecognition> | null>(
    null,
  );

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) setSupported(false);
  }, []);

  const startRecording = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) return;

    const recognition = new SR();
    recognition.lang = "ko-KR";
    recognition.continuous = true;
    recognition.interimResults = true;

    let finalTranscript = "";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result[0]) {
          if ((result as unknown as { isFinal: boolean }).isFinal) {
            finalTranscript += result[0].transcript + " ";
          } else {
            interim = result[0].transcript;
          }
        }
      }
      setTranscript(finalTranscript + interim);
    };

    recognition.onerror = () => {
      setStatus("idle");
    };

    recognition.onend = () => {
      if (status === "recording") {
        // 자동 종료 시 처리
        handleProcess(finalTranscript.trim());
      }
    };

    recognition.start();
    recognitionRef.current = recognition;
    setStatus("recording");
    setTranscript("");
  };

  const stopRecording = () => {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
    }
    handleProcess(transcript.trim());
  };

  const handleProcess = async (text: string) => {
    if (!text) {
      setStatus("idle");
      return;
    }
    setStatus("processing");
    const result = await parseSTT(text);
    if (result) {
      onParsed(result);
    }
    setStatus("idle");
    setTranscript("");
  };

  if (!supported) {
    return (
      <div className="p-3 bg-gray-50 rounded-lg text-sm text-gray-500 text-center">
        이 브라우저는 음성 입력을 지원하지 않습니다. Chrome을 사용해주세요.
      </div>
    );
  }

  return (
    <div className="card space-y-3">
      <div className="flex items-center gap-3">
        {status === "idle" && (
          <button
            onClick={startRecording}
            className="flex items-center gap-2 px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 cursor-pointer transition-colors"
          >
            <MdMic className="text-lg" /> 음성 입력 시작
          </button>
        )}

        {status === "recording" && (
          <button
            onClick={stopRecording}
            className="flex items-center gap-2 px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-800 cursor-pointer transition-colors animate-pulse"
          >
            <MdStop className="text-lg" /> 녹음 중... 탭하여 완료
          </button>
        )}

        {status === "processing" && (
          <div className="flex items-center gap-2 px-4 py-2 bg-blue-100 text-blue-700 rounded-lg">
            <MdAutorenew className="text-lg animate-spin" /> AI 분석 중...
          </div>
        )}
      </div>

      {transcript && (
        <div className="p-3 bg-gray-50 rounded-lg">
          <p className="text-xs text-gray-400 mb-1">인식된 텍스트</p>
          <p className="text-sm text-gray-700">{transcript}</p>
        </div>
      )}
    </div>
  );
}

// Web Speech API 타입 확장
function createRecognition() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  return new SR();
}

declare global {
  interface Window {
    SpeechRecognition: new () => {
      lang: string;
      continuous: boolean;
      interimResults: boolean;
      onresult: ((event: SpeechRecognitionEvent) => void) | null;
      onerror: ((event: unknown) => void) | null;
      onend: (() => void) | null;
      start: () => void;
      stop: () => void;
    };
    webkitSpeechRecognition: typeof window.SpeechRecognition;
  }
}

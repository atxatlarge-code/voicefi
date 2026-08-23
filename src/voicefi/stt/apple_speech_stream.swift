import Foundation
import Speech
import AVFoundation

class NativeAppleStreamer {
    private let recognizer: SFSpeechRecognizer
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()
    private var isRunning = false

    init(localeIdentifier: String = "en-US") {
        self.recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)) ?? SFSpeechRecognizer()!
    }

    func start() {
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            guard let self = self else { return }
            switch status {
            case .authorized:
                self.startRecording()
            case .denied, .restricted, .notDetermined:
                let errJson = "{\"type\": \"error\", \"message\": \"Apple Speech permission not granted\"}\n"
                fputs(errJson, stderr)
                exit(1)
            @unknown default:
                exit(1)
            }
        }
    }

    private func startRecording() {
        if isRunning { return }
        isRunning = true

        let inputNode = audioEngine.inputNode
        inputNode.removeTap(onBus: 0)

        request = SFSpeechAudioBufferRecognitionRequest()
        guard let request = request else { return }
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self = self else { return }

            if let result = result {
                let text = result.bestTranscription.formattedString
                let isFinal = result.isFinal
                
                var dict: [String: Any] = [
                    "type": isFinal ? "transcript" : "interim_transcript",
                    "text": text,
                    "is_final": isFinal,
                    "timestamp": Date().timeIntervalSince1970
                ]
                
                if let data = try? JSONSerialization.data(withJSONObject: dict),
                   let str = String(data: data, encoding: .utf8) {
                    print(str)
                    fflush(stdout)
                }
            }

            if let error = error {
                let nsError = error as NSError
                // 216 is recognition cancelled/finished normally
                if nsError.code != 216 && nsError.code != 209 {
                    // Retry session
                    self.restartTask()
                }
            }
        }

        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { buffer, _ in
            self.request?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
            let readyJson = "{\"type\": \"status\", \"state\": \"listening\"}\n"
            fputs(readyJson, stderr)
        } catch {
            let errJson = "{\"type\": \"error\", \"message\": \"\(error.localizedDescription)\"}\n"
            fputs(errJson, stderr)
        }
    }

    private func restartTask() {
        task?.cancel()
        task = nil
        request?.endAudio()
        request = nil
        
        request = SFSpeechAudioBufferRecognitionRequest()
        request?.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition {
            request?.requiresOnDeviceRecognition = true
        }
        guard let req = request else { return }

        task = recognizer.recognitionTask(with: req) { result, error in
            if let result = result {
                let text = result.bestTranscription.formattedString
                let isFinal = result.isFinal
                let dict: [String: Any] = [
                    "type": isFinal ? "transcript" : "interim_transcript",
                    "text": text,
                    "is_final": isFinal,
                    "timestamp": Date().timeIntervalSince1970
                ]
                if let data = try? JSONSerialization.data(withJSONObject: dict),
                   let str = String(data: data, encoding: .utf8) {
                    print(str)
                    fflush(stdout)
                }
            }
        }
    }

    func stop() {
        isRunning = false
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        task = nil
        request = nil
    }
}

let streamer = NativeAppleStreamer()
streamer.start()

// Keep runloop alive
RunLoop.main.run()

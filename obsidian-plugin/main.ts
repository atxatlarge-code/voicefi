import { App, Editor, MarkdownView, Modal, Notice, Plugin, PluginSettingTab, Setting, addIcon, requestUrl } from 'obsidian';
import { exec } from 'child_process';
import * as util from 'util';

const execPromise = util.promisify(exec);

const VOICEFI_ICON_SVG = `<path d="M 25 20 A 28 28 0 0 1 75 20" stroke="currentColor" stroke-width="6.5" stroke-linecap="round" fill="none"/>
<path d="M 34 30 A 18 18 0 0 1 66 30" stroke="currentColor" stroke-width="6" stroke-linecap="round" fill="none"/>
<path d="M 26 36 C 26 66 36 72 50 72 C 64 72 74 66 74 36" stroke="currentColor" stroke-width="5.5" stroke-linecap="round" fill="none"/>
<circle cx="39" cy="48" r="5" fill="currentColor"/>
<circle cx="61" cy="48" r="5" fill="currentColor"/>
<path d="M 39 59 Q 50 67 61 59" stroke="currentColor" stroke-width="4.5" stroke-linecap="round" fill="none"/>
<path d="M 18 44 C 18 74 30 81 50 81 C 70 81 82 74 82 44" stroke="currentColor" stroke-width="5.5" stroke-linecap="round" fill="none"/>
<line x1="50" y1="81" x2="50" y2="88" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
<line x1="36" y1="88" x2="64" y2="88" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>`;

interface VoiceFiSettings {
	vifiPath: string;
	audioCues: boolean;
	companionPort: number;
}

const DEFAULT_SETTINGS: VoiceFiSettings = {
	vifiPath: 'vifi',
	audioCues: true,
	companionPort: 5141
}

export default class VoiceFiPlugin extends Plugin {
	settings: VoiceFiSettings;
	private socket: WebSocket | null = null;
	private isListening: boolean = false;
	private ribbonIconEl: HTMLElement;
	private statusBarItemEl: HTMLElement;

	async onload() {
		await this.loadSettings();

		// Register custom VoiceFi logo icon
		addIcon('voicefi-logo', VOICEFI_ICON_SVG);

		// Add status bar item
		this.statusBarItemEl = this.addStatusBarItem();
		this.updateStatus('Standby', '🎙️');

		// Create the ribbon icon with VoiceFi official logo
		this.ribbonIconEl = this.addRibbonIcon('voicefi-logo', 'VoiceFi: Toggle Active Listening', (evt: MouseEvent) => {
			this.toggleListening();
		});

		// Add command for hotkey binding
		this.addCommand({
			id: 'toggle-active-listening',
			name: 'Toggle Active Listening Session',
			callback: () => {
				this.toggleListening();
			}
		});

		// Add command to speak current note or selection
		this.addCommand({
			id: 'speak-current-note',
			name: 'Read Selection or Note Aloud (TTS)',
			editorCallback: async (editor: Editor, view: MarkdownView) => {
				const text = editor.getSelection() || view.data;
				if (text.trim().length > 0) {
					this.updateStatus('Speaking...', '🔊');
					new Notice('VoiceFi: Speaking note...');
					await this.speakText(text);
					this.updateStatus(this.isListening ? 'Listening...' : 'Standby', this.isListening ? '🔴' : '🎙️');
				} else {
					new Notice('VoiceFi: Note or selection is empty.');
				}
			}
		});

		// Add command to ask Christopher about note
		this.addCommand({
			id: 'ask-christopher-about-note',
			name: 'Ask Christopher About Active Note (Voice Q&A)',
			editorCallback: async (editor: Editor, view: MarkdownView) => {
				const title = view.file ? view.file.basename : '';
				const content = editor.getValue() || view.data;
				new Notice(`🧠 Christopher is analyzing "${title}"...`);
				await this.askVaultAgent("Summarize this note", title, content);
			}
		});

		// Add the settings tab
		this.addSettingTab(new VoiceFiSettingTab(this.app, this));
	}

	updateStatus(status: string, icon: string = '🎙️') {
		if (this.statusBarItemEl) {
			this.statusBarItemEl.setText(`${icon} VoiceFi: ${status}`);
		}
	}

	onunload() {
		this.disconnectCompanion();
	}

	async loadSettings() {
		this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
	}

	async saveSettings() {
		await this.saveData(this.settings);
	}

	toggleListening() {
		if (this.isListening) {
			this.stopListening();
		} else {
			this.startListening();
		}
	}

	startListening() {
		if (this.isListening) return;
		this.isListening = true;
		this.updateIcon(true);
		this.updateStatus('Listening...', '🔴');
		new Notice('VoiceFi: Active Listening Started');
		this.connectCompanion();
	}

	stopListening() {
		if (!this.isListening) return;
		this.isListening = false;
		this.updateIcon(false);
		this.updateStatus('Standby', '🎙️');
		new Notice('VoiceFi: Active Listening Stopped');
		this.disconnectCompanion();
	}

	updateIcon(active: boolean) {
		if (active) {
			this.ribbonIconEl.style.color = 'var(--text-error)'; // Red for recording
		} else {
			this.ribbonIconEl.style.color = ''; // Reset
		}
	}

	async connectCompanion(canRetry: boolean = true) {
		if (this.socket) {
			this.socket.onopen = null;
			this.socket.onmessage = null;
			this.socket.onclose = null;
			this.socket.onerror = null;
			try {
				this.socket.close();
			} catch (e) {}
			this.socket = null;
		}

		try {
			const ws = new WebSocket(`ws://127.0.0.1:${this.settings.companionPort}/ws`);
			this.socket = ws;

			ws.onopen = () => {
				if (this.socket !== ws) return;
				console.log('VoiceFi Companion connected.');
				this.isListening = true;
				this.updateIcon(true);
				this.updateStatus('Listening...', '🔴');
				ws.send(JSON.stringify({ type: 'ambient_start', source: 'mic' }));
			};

			ws.onmessage = async (event) => {
				if (this.socket !== ws) return;
				try {
					const data = JSON.parse(event.data);
					if (data.type === 'interim_transcript') {
						this.updateStatus('Typing...', '✍️');
						await this.handleInterim(data.text);
					} else if (data.type === 'transcript' || data.type === 'ambient_utterance') {
						this.updateStatus('Listening...', '🔴');
						await this.handleTranscript(data.text);
					} else if (data.type === 'ambient_energy' && data.is_speech) {
						this.updateStatus('Hearing voice...', '🗣️');
					} else if (data.type === 'agent_speaking_started') {
						this.updateStatus('Agent Speaking...', '🔊');
					} else if (data.type === 'agent_speaking_finished') {
						this.updateStatus('Listening...', '🔴');
					}
				} catch (e) {
					console.error('Error parsing VoiceFi message:', e);
				}
			};

			ws.onclose = () => {
				if (this.socket === ws) {
					console.log('VoiceFi Companion disconnected.');
					this.socket = null;
					if (this.isListening) {
						this.stopListening();
					}
				}
			};

			ws.onerror = async (error) => {
				if (this.socket !== ws) return;
				if (canRetry) {
					try {
						new Notice('VoiceFi: Connecting background engine...');
						const cmd = `nohup "${this.settings.vifiPath}" companion --port ${this.settings.companionPort} --no-qr > /tmp/voicefi_companion.log 2>&1 &`;
						await execPromise(cmd);
						setTimeout(() => {
							this.connectCompanion(false);
						}, 1200);
						return;
					} catch (e) {
						console.error('Auto-start error:', e);
					}
				}
				console.error('VoiceFi WebSocket Error:', error);
				new Notice('VoiceFi: Companion server unreachable.');
				this.stopListening();
			};

		} catch (e) {
			console.error(e);
			new Notice('VoiceFi: Failed to connect to companion server.');
			this.stopListening();
		}
	}

	disconnectCompanion() {
		if (this.socket) {
			if (this.socket.readyState === WebSocket.OPEN) {
				try {
					this.socket.send(JSON.stringify({ type: 'ambient_stop' }));
				} catch (e) {}
			}
			this.socket.onopen = null;
			this.socket.onmessage = null;
			this.socket.onclose = null;
			this.socket.onerror = null;
			this.socket.close();
			this.socket = null;
		}
	}

	private interimStart: { line: number, ch: number } | null = null;

	async handleInterim(text: string) {
		const cleanText = text.trim();
		if (!cleanText) return;

		// If this is an agent command in progress, suppress typing onto note canvas
		if (/^(hey\s+christopher|hey\s+voicefi|voicefi|hey\s+agent|christopher|summarize)/i.test(cleanText)) {
			this.updateStatus('Asking Christopher...', '🧠');
			return;
		}

		const activeView = this.app.workspace.getActiveViewOfType(MarkdownView);
		if (!activeView) return;

		const editor = activeView.editor;
		const cursor = editor.getCursor();

		if (!this.interimStart) {
			this.interimStart = { line: cursor.line, ch: cursor.ch };
		}

		// Atomically replace from original start position to current cursor with live words
		editor.replaceRange(cleanText, this.interimStart, cursor);
		editor.setCursor({
			line: this.interimStart.line,
			ch: this.interimStart.ch + cleanText.length
		});
	}

	async handleTranscript(text: string) {
		let cleanText = text.trim();
		if (!cleanText) return;

		const activeView = this.app.workspace.getActiveViewOfType(MarkdownView);
		if (!activeView) return;

		const editor = activeView.editor;
		const cursor = editor.getCursor();
		const startPos = this.interimStart ? { ...this.interimStart } : { ...cursor };
		this.interimStart = null; // Reset anchor for next utterance

		// 1. Check for Conversational Agent Wake Words & Intent Commands FIRST
		let checkText = cleanText;
		// Phonetic normalization for Whisper acoustic slips
		if (/some\s+(racist|raise|race|race\s+is|eyes)/i.test(checkText)) {
			checkText = checkText.replace(/some\s+(racist|raise|race|race\s+is|eyes)/i, 'summarize');
		}

		const agentMatch = checkText.match(/^(hey\s+christopher|hey\s+voicefi|voicefi|hey\s+agent|christopher)[,.:!?\s]+(.*)$/i);
		const isDirectCommand = /^(summarize(\s+this)?(\s+note)?|what\s+are\s+my\s+(tasks|action\s+items|todos)|what\s+is\s+this\s+note\s+about)[,.:!?\s]*$/i.test(checkText);

		if (agentMatch || isDirectCommand) {
			const query = agentMatch ? agentMatch[2].trim() : checkText;
			if (query.length > 0) {
				// Clear any interim preview text from editor so command is never typed
				editor.replaceRange('', startPos, cursor);
				editor.setCursor(startPos);
				
				this.updateStatus('Thinking...', '🧠');
				new Notice(`🧠 VoiceFi: Asking Christopher: "${query}"...`);
				
				const title = activeView.file ? activeView.file.basename : '';
				const content = activeView.editor.getValue() || activeView.data;
				
				await this.askVaultAgent(query, title, content);
				return;
			}
		}

		// 2. Smart Spoken Markdown Formatter for standard dictation
		let insertText = cleanText;
		const lower = cleanText.toLowerCase();

		if (lower === 'new line' || lower === 'newline' || lower === 'new line.') {
			editor.replaceRange('\n', startPos, cursor);
			editor.setCursor({ line: startPos.line + 1, ch: 0 });
			return;
		} else if (lower === 'new paragraph' || lower === 'new paragraph.') {
			editor.replaceRange('\n\n', startPos, cursor);
			editor.setCursor({ line: startPos.line + 2, ch: 0 });
			return;
		} else if (lower.startsWith('bullet ') || lower.startsWith('dash ')) {
			insertText = '\n- ' + cleanText.replace(/^(bullet|dash)\s+/i, '') + ' ';
		} else if (lower.startsWith('task ') || lower.startsWith('todo ') || lower.startsWith('checkbox ')) {
			insertText = '\n- [ ] ' + cleanText.replace(/^(task|todo|checkbox)\s+/i, '') + ' ';
		} else if (lower.startsWith('heading one ') || lower.startsWith('heading 1 ')) {
			insertText = '\n# ' + cleanText.replace(/^(heading one|heading 1)\s+/i, '') + '\n';
		} else if (lower.startsWith('heading two ') || lower.startsWith('heading 2 ')) {
			insertText = '\n## ' + cleanText.replace(/^(heading two|heading 2)\s+/i, '') + '\n';
		} else if (lower.startsWith('heading three ') || lower.startsWith('heading 3 ')) {
			insertText = '\n### ' + cleanText.replace(/^(heading three|heading 3)\s+/i, '') + '\n';
		} else {
			insertText = cleanText + ' ';
		}

		// Directly replace the interim words with the final polished text
		editor.replaceRange(insertText, startPos, cursor);

		// Advance cursor forward cleanly
		const lines = insertText.split('\n');
		if (lines.length > 1) {
			const lastLine = lines[lines.length - 1];
			editor.setCursor({
				line: startPos.line + lines.length - 1,
				ch: lastLine.length
			});
		} else {
			editor.setCursor({
				line: startPos.line,
				ch: startPos.ch + insertText.length
			});
		}
	}

	async askVaultAgent(query: string, title: string, content: string) {
		try {
			const res = await requestUrl({
				url: `http://127.0.0.1:${this.settings.companionPort}/api/vault/query`,
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					query: query,
					note_title: title,
					note_content: content,
					speak: true
				})
			});
			if (res.status === 200) {
				const data = res.json;
				if (data.spoken_response) {
					new Notice(`🧔 Christopher: "${data.spoken_response}"`, 9000);
				}
			} else {
				new Notice('VoiceFi: Failed to query vault agent.');
			}
		} catch (e) {
			console.error('Vault agent error:', e);
			new Notice('VoiceFi: Companion server unreachable.');
		} finally {
			if (this.isListening) {
				this.updateStatus('Listening...', '🔴');
			} else {
				this.updateStatus('Standby', '🎙️');
			}
		}
	}

	async speakText(text: string) {
		try {
			// 1. Try Companion HTTP API first (fast & reliable with requestUrl)
			const res = await requestUrl({
				url: `http://127.0.0.1:${this.settings.companionPort}/api/tts`,
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ text: text })
			});
			if (res.status === 200) return;
		} catch (e) {}

		try {
			// 2. Fallback to CLI
			const escapedText = text.replace(/"/g, '\\"');
			await execPromise(`"${this.settings.vifiPath}" speak "${escapedText}"`);
		} catch (error) {
			console.error('VoiceFi TTS Error:', error);
			new Notice('VoiceFi: Failed to speak text.');
		}
	}
}

class VoiceFiSettingTab extends PluginSettingTab {
	plugin: VoiceFiPlugin;

	constructor(app: App, plugin: VoiceFiPlugin) {
		super(app, plugin);
		this.plugin = plugin;
	}

	display(): void {
		const {containerEl} = this;

		containerEl.empty();
		containerEl.createEl('h2', {text: 'VoiceFi Settings'});

		new Setting(containerEl)
			.setName('CLI Path')
			.setDesc('Path to the vifi executable (or just "vifi" if in PATH).')
			.addText(text => text
				.setPlaceholder('vifi')
				.setValue(this.plugin.settings.vifiPath)
				.onChange(async (value) => {
					this.plugin.settings.vifiPath = value;
					await this.plugin.saveSettings();
				}));

		new Setting(containerEl)
			.setName('Companion Port')
			.setDesc('Port for the local VoiceFi Companion server.')
			.addText(text => text
				.setPlaceholder('5141')
				.setValue(this.plugin.settings.companionPort.toString())
				.onChange(async (value) => {
					this.plugin.settings.companionPort = parseInt(value) || 5141;
					await this.plugin.saveSettings();
				}));

		new Setting(containerEl)
			.setName('Audio Cues')
			.setDesc('Play chimes when listening starts and stops.')
			.addToggle(toggle => toggle
				.setValue(this.plugin.settings.audioCues)
				.onChange(async (value) => {
					this.plugin.settings.audioCues = value;
					await this.plugin.saveSettings();
				}));
	}
}

/**
 * Mistral-TTS-Booksmith - Frontend Application Logic
 * Implements API key management, form tab controls, translation toggles,
 * drag-and-drop file zones, form submission, and SSE progress tracking.
 */

document.addEventListener('DOMContentLoaded', () => {
    // === DOM Element References ===
    const generatorForm = document.getElementById('generator-form');
    const apiKeyInput = document.getElementById('api-key');
    const toggleApiVisibilityBtn = document.getElementById('toggle-api-visibility');
    const translationToggle = document.getElementById('translation-toggle');
    const translationSubform = document.getElementById('translation-subform');
    
    const submitBtn = document.getElementById('submit-btn');
    const submitBtnText = submitBtn.querySelector('.submit-btn-text');
    
    const progressCard = document.getElementById('progress-card');
    const statusBadge = document.getElementById('status-badge');
    const progressPercentage = document.getElementById('progress-percentage');
    const progressBar = document.getElementById('progress-bar');
    const consoleLogs = document.getElementById('console-logs');
    const clearConsoleBtn = document.getElementById('clear-console-btn');
    
    const playerCard = document.getElementById('player-card');
    const audioPlayer = document.getElementById('audio-player');
    const downloadBtn = document.getElementById('download-btn');
    
    let eventSource = null;
    let isFinished = false;
    let renderedLogCount = 0;
    
    // === 1. API Key Management ===
    // Load saved API key
    const savedApiKey = localStorage.getItem('api_key');
    if (savedApiKey) {
        apiKeyInput.value = savedApiKey;
    }
    
    // Toggle API Key visibility
    toggleApiVisibilityBtn.addEventListener('click', () => {
        const isPassword = apiKeyInput.type === 'password';
        apiKeyInput.type = isPassword ? 'text' : 'password';
        
        // Update the eye icon SVG to reflect current state
        if (isPassword) {
            // Change to eye-off (slashed) icon
            toggleApiVisibilityBtn.innerHTML = `
                <svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                    <line x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
            `;
        } else {
            // Change back to standard eye icon
            toggleApiVisibilityBtn.innerHTML = `
                <svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle cx="12" cy="12" r="3"></circle>
                </svg>
            `;
        }
    });

    // === 2. Form Tab Controls ===
    const voiceModeRadios = document.querySelectorAll('input[name="voice_mode"]');
    const voicePanels = {
        preset: document.getElementById('preset-voice-panel'),
        manual: document.getElementById('manual-voice-panel'),
        clone: document.getElementById('cloning-voice-panel')
    };

    function updateVoicePanels() {
        const selectedRadio = document.querySelector('input[name="voice_mode"]:checked');
        const selectedMode = selectedRadio ? selectedRadio.value : 'preset';
        Object.entries(voicePanels).forEach(([mode, panel]) => {
            if (panel) {
                if (mode === selectedMode) {
                    panel.classList.add('active');
                } else {
                    panel.classList.remove('active');
                }
            }
        });
    }

    voiceModeRadios.forEach(radio => {
        radio.addEventListener('change', updateVoicePanels);
    });
    
    // Initialize correct voice panel on load
    updateVoicePanels();

    // === 3. Translation Toggle ===
    translationToggle.addEventListener('change', () => {
        if (translationToggle.checked) {
            translationSubform.classList.remove('collapsed');
        } else {
            translationSubform.classList.add('collapsed');
        }
    });

    // === 4. Drag-and-Drop File Zones ===
    function setupDropzone(dropzoneId, inputId, fileNameId, defaultText) {
        const dropzone = document.getElementById(dropzoneId);
        const input = document.getElementById(inputId);
        const fileNameEl = document.getElementById(fileNameId);

        if (!dropzone || !input || !fileNameEl) return;

        // Prevent default behaviors for drag events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            input.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Toggle dragover class on hover
        ['dragenter', 'dragover'].forEach(eventName => {
            input.addEventListener(eventName, () => {
                dropzone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            input.addEventListener(eventName, () => {
                dropzone.classList.remove('dragover');
            }, false);
        });

        // Handle dropped files
        input.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length) {
                input.files = files;
                updateFileName(files[0]);
            }
        }, false);

        // Handle selected files (via browse click)
        input.addEventListener('change', () => {
            if (input.files.length) {
                updateFileName(input.files[0]);
            } else {
                clearFileName();
            }
        });

        function updateFileName(file) {
            fileNameEl.textContent = file.name;
            dropzone.classList.add('has-file');
        }

        function clearFileName() {
            fileNameEl.textContent = defaultText;
            dropzone.classList.remove('has-file');
        }
    }

    setupDropzone('text-dropzone', 'text-file', 'text-file-name', 'No file selected');
    setupDropzone('voice-dropzone', 'voice-file', 'voice-file-name', 'No audio selected');

    // === 7. Console Action Button ===
    clearConsoleBtn.addEventListener('click', () => {
        consoleLogs.innerHTML = '';
        renderedLogCount = 0; // Reset log count to allow fresh render if streaming is active
    });

    // Helper to append a formatted console line
    function appendConsoleLine(text, type = '') {
        const lineEl = document.createElement('div');
        lineEl.classList.add('console-line');
        if (type) {
            lineEl.classList.add(type);
        }
        lineEl.textContent = text;
        consoleLogs.appendChild(lineEl);
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    // === 5. Form Submission & API Handshake ===
    generatorForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        
        // --- Validation ---
        const apiKey = apiKeyInput.value.trim();
        if (!apiKey) {
            alert('Please enter your Mistral API Key.');
            apiKeyInput.focus();
            return;
        }

        const textFileInput = document.getElementById('text-file');
        const textContentInput = document.getElementById('text-content');
        const hasTextFile = textFileInput.files && textFileInput.files.length > 0;
        const hasTextContent = textContentInput.value.trim().length > 0;

        if (!hasTextFile && !hasTextContent) {
            alert('Please upload a text file (.txt, .srt) or paste text content manually.');
            textContentInput.focus();
            return;
        }
        
        // Save API key to localStorage
        localStorage.setItem('api_key', apiKey);

        // --- Form Data Assembly & Cleanup ---
        const formData = new FormData(generatorForm);
        const voiceMode = formData.get('voice_mode');
        
        // Clean conflicting voice parameters
        if (voiceMode === 'preset') {
            formData.delete('voice_file');
            formData.delete('voice_manual_id');
        } else if (voiceMode === 'manual') {
            formData.delete('voice_file');
            formData.delete('voice_preset');
        } else if (voiceMode === 'clone') {
            formData.delete('voice_preset');
            formData.delete('voice_manual_id');
        }

        // Clean translation parameters if not enabled
        if (!translationToggle.checked) {
            formData.delete('source_lang');
            formData.delete('target_lang');
        }

        // --- UI Transition ---
        // Disable submit button
        submitBtn.disabled = true;
        const originalBtnText = submitBtnText.textContent;
        submitBtnText.textContent = 'Synthesizing...';

        // Show progress card, hide player card
        progressCard.classList.remove('hidden');
        playerCard.classList.add('hidden');

        // Reset progress bar & console logs
        progressBar.style.width = '0%';
        progressPercentage.textContent = '0%';
        statusBadge.textContent = 'Connecting';
        statusBadge.className = 'badge'; // Reset classes
        consoleLogs.innerHTML = '';
        renderedLogCount = 0;
        isFinished = false;

        appendConsoleLine('Connecting to pipeline...', 'system-line');

        // Scroll smoothly to the progress card
        progressCard.scrollIntoView({ behavior: 'smooth' });

        // --- Post Request & EventSource Connection ---
        try {
            const response = await fetch('/api/generate', {
                method: 'POST',
                body: formData
            });

            if (!response.ok) {
                const errorText = await response.text();
                let errorMsg = `Server returned status ${response.status}`;
                try {
                    const errorJson = JSON.parse(errorText);
                    if (errorJson.detail) {
                        errorMsg = errorJson.detail;
                    } else if (errorJson.error) {
                        errorMsg = errorJson.error;
                    }
                } catch (_) {}
                throw new Error(errorMsg);
            }

            const data = await response.json();
            const taskId = data.task_id;
            if (!taskId) {
                throw new Error('No task ID returned from backend.');
            }

            appendConsoleLine(`Task initialized successfully (ID: ${taskId}). Subscribing to progress updates...`, 'system-line');
            startProgressStream(taskId, originalBtnText);

        } catch (error) {
            appendConsoleLine(`Initialization Failed: ${error.message}`, 'error-line');
            statusBadge.textContent = 'Failed';
            statusBadge.className = 'badge error';
            
            // Re-enable submit button
            submitBtn.disabled = false;
            submitBtnText.textContent = originalBtnText;
            
            alert(`Failed to start generation: ${error.message}`);
        }
    });

    // === 6. SSE Stream Tracking ===
    function startProgressStream(taskId, originalBtnText) {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource(`/api/progress?task_id=${taskId}`);

        eventSource.onmessage = (event) => {
            if (isFinished) return;

            try {
                const state = JSON.parse(event.data);
                
                // Update badge and progress bar
                if (state.status) {
                    statusBadge.textContent = state.status;
                }
                
                if (state.percentage !== undefined) {
                    const pct = Math.min(100, Math.max(0, state.percentage));
                    progressBar.style.width = `${pct}%`;
                    progressPercentage.textContent = `${pct}%`;
                }

                // Render new logs
                const logs = state.logs || [];
                if (logs.length > renderedLogCount) {
                    for (let i = renderedLogCount; i < logs.length; i++) {
                        const lineText = logs[i];
                        
                        // Determine line class based on keywords
                        let lineClass = '';
                        if (/error|fail/i.test(lineText)) {
                            lineClass = 'error-line';
                        } else if (/success|compiled/i.test(lineText)) {
                            lineClass = 'success-line';
                        } else if (/translating|splitting|voice/i.test(lineText)) {
                            lineClass = 'system-line';
                        }
                        
                        appendConsoleLine(lineText, lineClass);
                    }
                    renderedLogCount = logs.length;
                }

                // Check for completion
                if (state.completed || state.status === 'Completed') {
                    handleTaskSuccess(state.audio_file, originalBtnText);
                } 
                // Check for error
                else if (state.error || state.status === 'Failed') {
                    handleTaskFailure(state.error || 'Pipeline execution failed.', originalBtnText);
                }

            } catch (err) {
                console.error('Error parsing progress data:', err);
            }
        };

        eventSource.onerror = (err) => {
            if (isFinished) return;
            console.error('EventSource connection error:', err);
            
            // Log connection loss and clean up
            appendConsoleLine('Lost connection to progress monitoring pipeline.', 'error-line');
            handleTaskFailure('Progress stream connection lost.', originalBtnText);
        };
    }

    function handleTaskSuccess(audioFile, originalBtnText) {
        isFinished = true;
        if (eventSource) {
            eventSource.close();
        }

        // Force progress to 100%
        progressBar.style.width = '100%';
        progressPercentage.textContent = '100%';
        statusBadge.textContent = 'Completed';
        
        appendConsoleLine('Audiobook compiled successfully!', 'success-line');

        // Configure audio player & download link
        const audioUrl = `/api/audio/${encodeURIComponent(audioFile)}`;
        audioPlayer.src = audioUrl;
        downloadBtn.href = audioUrl;
        audioPlayer.load();

        // Reveal playback card
        playerCard.classList.remove('hidden');

        // Scroll smoothly to playback card
        playerCard.scrollIntoView({ behavior: 'smooth' });

        // Re-enable submit button
        submitBtn.disabled = false;
        submitBtnText.textContent = originalBtnText;
    }

    function handleTaskFailure(errorMessage, originalBtnText) {
        isFinished = true;
        if (eventSource) {
            eventSource.close();
        }

        statusBadge.textContent = 'Failed';
        appendConsoleLine(`Error: ${errorMessage}`, 'error-line');

        // Re-enable submit button
        submitBtn.disabled = false;
        submitBtnText.textContent = originalBtnText;
    }
});

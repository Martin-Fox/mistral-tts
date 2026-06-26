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
    const engineSelect = document.getElementById('engine');
    const openaiKeyInput = document.getElementById('openai-key');
    const toggleOpenaiVisibilityBtn = document.getElementById('toggle-openai-visibility');
    const openaiKeyGroup = document.getElementById('openai-key-group');
    const mistralKeyGroup = document.getElementById('mistral-key-group');
    
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
    const savedOpenaiKey = localStorage.getItem('openai_key');
    if (savedOpenaiKey && openaiKeyInput) {
        openaiKeyInput.value = savedOpenaiKey;
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

    // Toggle OpenAI API Key visibility
    if (toggleOpenaiVisibilityBtn && openaiKeyInput) {
        toggleOpenaiVisibilityBtn.addEventListener('click', () => {
            const isPassword = openaiKeyInput.type === 'password';
            openaiKeyInput.type = isPassword ? 'text' : 'password';
            
            // Update the eye icon SVG to reflect current state
            if (isPassword) {
                // Change to eye-off (slashed) icon
                toggleOpenaiVisibilityBtn.innerHTML = `
                    <svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path>
                        <line x1="1" y1="1" x2="23" y2="23"></line>
                    </svg>
                `;
            } else {
                // Change back to standard eye icon
                toggleOpenaiVisibilityBtn.innerHTML = `
                    <svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                        <circle cx="12" cy="12" r="3"></circle>
                    </svg>
                `;
            }
        });
    }

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

    // === 2b. TTS Engine & Voice Preset Selection ===
    const MISTRAL_VOICE_HTML = `
        <optgroup label="English (US)">
            <option value="en_paul_neutral" selected>Paul - Neutral (Male)</option>
            <option value="en_paul_cheerful">Paul - Cheerful (Male)</option>
            <option value="en_paul_confident">Paul - Confident (Male)</option>
            <option value="en_paul_excited">Paul - Excited (Male)</option>
        </optgroup>
        <optgroup label="English (UK)">
            <option value="gb_oliver_neutral">Oliver - Neutral (Male)</option>
            <option value="gb_oliver_cheerful">Oliver - Cheerful (Male)</option>
            <option value="gb_jane_neutral">Jane - Neutral (Female)</option>
            <option value="gb_jane_confident">Jane - Confident (Female)</option>
            <option value="gb_jane_sarcasm">Jane - Sarcasm (Female)</option>
        </optgroup>
        <optgroup label="French">
            <option value="fr_marie_neutral">Marie - Neutral (Female)</option>
            <option value="fr_marie_happy">Marie - Happy (Female)</option>
            <option value="fr_marie_excited">Marie - Excited (Female)</option>
            <option value="fr_marie_curious">Marie - Curious (Female)</option>
        </optgroup>
    `;

    const OPENAI_VOICE_HTML = `
        <optgroup label="OpenAI Presets">
            <option value="alloy" selected>Alloy</option>
            <option value="echo">Echo</option>
            <option value="fable">Fable</option>
            <option value="onyx">Onyx</option>
            <option value="nova">Nova</option>
            <option value="shimmer">Shimmer</option>
        </optgroup>
    `;

    if (engineSelect) {
        engineSelect.addEventListener('change', () => {
            const isOpenAI = engineSelect.value === 'openai';
            
            // Toggle API key visibility groups
            if (isOpenAI) {
                if (openaiKeyGroup) openaiKeyGroup.style.display = 'block';
                if (mistralKeyGroup) mistralKeyGroup.style.display = 'none';
            } else {
                if (openaiKeyGroup) openaiKeyGroup.style.display = 'none';
                if (mistralKeyGroup) mistralKeyGroup.style.display = 'block';
            }
            
            // Update voice list presets
            const voicePresetSelect = document.getElementById('voice-preset');
            if (voicePresetSelect) {
                voicePresetSelect.innerHTML = isOpenAI ? OPENAI_VOICE_HTML : MISTRAL_VOICE_HTML;
            }
            
            // Tab controls
            const presetRadio = document.querySelector('input[name="voice_mode"][value="preset"]');
            const manualRadio = document.querySelector('input[name="voice_mode"][value="manual"]');
            const cloneRadio = document.querySelector('input[name="voice_mode"][value="clone"]');
            
            if (manualRadio && cloneRadio) {
                const manualLabel = manualRadio.closest('.tab-button');
                const cloneLabel = cloneRadio.closest('.tab-button');
                
                if (isOpenAI) {
                    // Disable manual and clone
                    manualRadio.disabled = true;
                    cloneRadio.disabled = true;
                    
                    // Add disabled class to labels
                    if (manualLabel) manualLabel.classList.add('disabled');
                    if (cloneLabel) cloneLabel.classList.add('disabled');
                    
                    // Force preset to be checked
                    if (presetRadio) {
                        presetRadio.checked = true;
                    }
                    
                    // Activate preset panel
                    updateVoicePanels();
                } else {
                    // Enable manual and clone
                    manualRadio.disabled = false;
                    cloneRadio.disabled = false;
                    
                    // Remove disabled class from labels
                    if (manualLabel) manualLabel.classList.remove('disabled');
                    if (cloneLabel) cloneLabel.classList.remove('disabled');
                }
            }
        });

        // Trigger once on initialization to sync with current select state
        engineSelect.dispatchEvent(new Event('change'));
    }

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

        const textFileInput = document.getElementById('text-file');
        const textContentInput = document.getElementById('text-content');
        const hasTextFile = textFileInput.files && textFileInput.files.length > 0;
        const hasTextContent = textContentInput.value.trim().length > 0;

        if (!hasTextFile && !hasTextContent) {
            alert('Please upload a text file (.txt, .srt) or paste text content manually.');
            textContentInput.focus();
            return;
        }
        
        // Save or clear API key in localStorage
        if (apiKey) {
            localStorage.setItem('api_key', apiKey);
        } else {
            localStorage.removeItem('api_key');
        }

        const openaiKey = openaiKeyInput ? openaiKeyInput.value.trim() : '';
        if (openaiKey) {
            localStorage.setItem('openai_key', openaiKey);
        } else {
            localStorage.removeItem('openai_key');
        }


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

    // === 8. Change Password Form Handling ===
    const passwordForm = document.getElementById('password-form');
    const currentPasswordInput = document.getElementById('current-password');
    const newPasswordInput = document.getElementById('new-password');
    const confirmPasswordInput = document.getElementById('confirm-password');
    const passwordStatus = document.getElementById('password-status');
    const updatePasswordBtn = document.getElementById('update-password-btn');

    if (passwordForm) {
        passwordForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const currentPassword = currentPasswordInput.value;
            const newPassword = newPasswordInput.value;
            const confirmPassword = confirmPasswordInput.value;
            
            // Client-side validation
            if (!currentPassword || !newPassword || !confirmPassword) {
                showPasswordStatus('Please fill in all fields.', 'error');
                return;
            }
            
            if (newPassword.length < 4) {
                showPasswordStatus('New password must be at least 4 characters long.', 'error');
                return;
            }
            
            if (newPassword !== confirmPassword) {
                showPasswordStatus('New passwords do not match.', 'error');
                return;
            }
            
            // Disable button during request
            updatePasswordBtn.disabled = true;
            showPasswordStatus('Updating password...', 'system');
            
            try {
                const response = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        current_password: currentPassword,
                        new_password: newPassword
                    })
                });
                
                if (response.ok) {
                    showPasswordStatus('Password updated successfully. The new password will be required on your next login.', 'success');
                    passwordForm.reset();
                } else {
                    const data = await response.json();
                    let errMsg = 'Failed to update password.';
                    if (data.detail) {
                        errMsg = data.detail;
                    }
                    showPasswordStatus(errMsg, 'error');
                }
            } catch (error) {
                showPasswordStatus(`Error: ${error.message}`, 'error');
            } finally {
                updatePasswordBtn.disabled = false;
            }
        });
    }

    function showPasswordStatus(message, type) {
        if (!passwordStatus) return;
        passwordStatus.textContent = message;
        passwordStatus.className = 'status-message'; // reset classes
        if (type) {
            passwordStatus.classList.add(type);
        }
    }

    // === 9. Toggle Settings Card ===
    const toggleSettingsBtn = document.getElementById('toggle-settings-btn');
    const settingsCard = document.getElementById('settings-card');

    if (toggleSettingsBtn && settingsCard) {
        toggleSettingsBtn.addEventListener('click', () => {
            settingsCard.classList.toggle('hidden');
            if (!settingsCard.classList.contains('hidden')) {
                settingsCard.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    // === 10. Session Cookie Authentication & Overlay Management ===
    const loginOverlay = document.getElementById('login-overlay');
    const loginForm = document.getElementById('login-form');
    const loginUsernameInput = document.getElementById('login-username');
    const loginPasswordInput = document.getElementById('login-password');
    const loginStatus = document.getElementById('login-status');
    const loginSubmitBtn = document.getElementById('login-submit-btn');
    const logoutBtn = document.getElementById('logout-btn');

    // Helper to display messages on the login screen
    function showLoginStatus(message, type) {
        if (!loginStatus) return;
        loginStatus.textContent = message;
        loginStatus.className = 'status-message';
        if (type) {
            loginStatus.classList.add(type);
        }
    }

    // Check auth status on page load
    async function checkAuthStatus() {
        try {
            const response = await fetch('/api/auth/status');
            const data = await response.json();
            if (data.authenticated) {
                if (loginOverlay) loginOverlay.classList.add('hidden');
            } else {
                if (loginOverlay) loginOverlay.classList.remove('hidden');
            }
        } catch (error) {
            console.error('Error checking auth status:', error);
            if (loginOverlay) loginOverlay.classList.remove('hidden');
        }
    }

    // Handle Login Form Submission
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const username = loginUsernameInput.value.trim();
            const password = loginPasswordInput.value;
            
            if (!username || !password) {
                showLoginStatus('Please enter both username and password.', 'error');
                return;
            }
            
            loginSubmitBtn.disabled = true;
            showLoginStatus('Signing in...', 'system');
            
            try {
                const response = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ username, password })
                });
                
                if (response.ok) {
                    showLoginStatus('Login successful.', 'success');
                    loginForm.reset();
                    setTimeout(() => {
                        if (loginOverlay) loginOverlay.classList.add('hidden');
                    }, 500);
                } else {
                    const data = await response.json();
                    const errMsg = data.detail || 'Incorrect username or password.';
                    showLoginStatus(errMsg, 'error');
                }
            } catch (error) {
                showLoginStatus(`Error: ${error.message}`, 'error');
            } finally {
                loginSubmitBtn.disabled = false;
            }
        });
    }

    // Handle Logout
    if (logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            if (confirm('Are you sure you want to log out?')) {
                try {
                    await fetch('/api/auth/logout', { method: 'POST' });
                } catch (error) {
                    console.error('Error during logout request:', error);
                } finally {
                    // Show login overlay again immediately and reset form
                    if (loginOverlay) loginOverlay.classList.remove('hidden');
                    if (settingsCard) settingsCard.classList.add('hidden');
                    showLoginStatus('Logged out successfully.', 'system');
                }
            }
        });
    }

    // Run auth status check on initialization
    checkAuthStatus();
});

// Web Speech API wrapper — voice input module

const Voice = (() => {
  const overlay   = document.getElementById('voiceOverlay');
  const statusEl  = document.getElementById('voiceStatus');
  const transcriptEl = document.getElementById('voiceTranscript');
  const resultEl  = document.getElementById('voiceResult');
  const cancelBtn = document.getElementById('voiceCancelBtn');
  const pulseEl   = document.querySelector('.voice-pulse');

  let recognition = null;
  let isListening = false;
  let finalText   = '';

  // Check browser support
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const supported = !!SpeechRecognition;

  function init() {
    if (!supported) return;
    recognition = new SpeechRecognition();
    recognition.lang = 'ru-RU';
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      isListening = true;
      setStatus('Слушаю...');
      transcriptEl.textContent = '';
      resultEl.textContent = '';
    };

    recognition.onresult = (e) => {
      let interim = '';
      let final = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) final += t;
        else interim += t;
      }
      if (final) finalText += final;
      transcriptEl.textContent = finalText || interim;
    };

    recognition.onend = () => {
      isListening = false;
      if (finalText.trim()) {
        sendToAPI(finalText.trim());
      } else {
        setStatus('Ничего не распознано');
        setTimeout(close, 1500);
      }
    };

    recognition.onerror = (e) => {
      isListening = false;
      if (e.error === 'no-speech') {
        setStatus('Ничего не услышала. Попробуйте ещё раз.');
        setTimeout(close, 2000);
      } else if (e.error === 'not-allowed') {
        setStatus('Нет доступа к микрофону');
        setTimeout(close, 2500);
      } else {
        setStatus(`Ошибка: ${e.error}`);
        setTimeout(close, 2000);
      }
    };
  }

  async function sendToAPI(text) {
    setStatus('Обрабатываю...');
    pulseEl.style.background = '#8B5CF6';
    try {
      const data = await API.sendVoice(text);
      resultEl.textContent = data.message;
      setStatus('Готово');
      // Notify app to refresh current screen
      window.dispatchEvent(new CustomEvent('voice-added', { detail: data }));
      setTimeout(close, 2000);
    } catch (err) {
      resultEl.textContent = `Ошибка: ${err.message}`;
      setStatus('Не удалось сохранить');
      setTimeout(close, 3000);
    }
  }

  function setStatus(text) {
    statusEl.textContent = text;
  }

  function open() {
    if (!supported) {
      App.showToast('Ваш браузер не поддерживает голосовой ввод. Попробуйте Chrome.');
      return;
    }
    finalText = '';
    pulseEl.style.background = 'var(--gold)';
    resultEl.textContent = '';
    overlay.classList.add('active');
    startListening();
  }

  function startListening() {
    if (!recognition) init();
    finalText = '';
    transcriptEl.textContent = '';
    try {
      recognition.start();
    } catch (e) {
      // Already started — stop and restart
      recognition.stop();
      setTimeout(() => { recognition.start(); }, 200);
    }
  }

  function close() {
    if (isListening && recognition) {
      try { recognition.stop(); } catch (_) {}
    }
    overlay.classList.remove('active');
    isListening = false;
    finalText = '';
  }

  // Cancel button
  cancelBtn.addEventListener('click', close);

  // Close on overlay background click
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  return { open, close, supported };
})();

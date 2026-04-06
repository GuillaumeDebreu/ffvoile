/* ─── VoileCV Frontend ─────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', () => {
    // ─── FAQ Accordion ──────────────────────────────────────────
    document.querySelectorAll('.faq-question').forEach(btn => {
        btn.addEventListener('click', () => {
            const item = btn.parentElement;
            const wasOpen = item.classList.contains('open');
            document.querySelectorAll('.faq-item').forEach(i => i.classList.remove('open'));
            if (!wasOpen) item.classList.add('open');
        });
    });

    // ─── Upload Zone ────────────────────────────────────────────
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('cv-file');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileRemove = document.getElementById('file-remove');
    const payBtn = document.getElementById('pay-btn');
    const emailInput = document.getElementById('email');

    if (!uploadZone) return; // Not on landing page

    let selectedFile = null;
    let diplomaFile = null;
    let letterFile = null;

    function updatePayBtn() {
        const hasFile = selectedFile !== null;
        const hasEmail = emailInput.value.includes('@');
        payBtn.disabled = !(hasFile && hasEmail);
    }

    emailInput.addEventListener('input', updatePayBtn);

    // CV upload
    uploadZone.addEventListener('click', () => fileInput.click());

    uploadZone.addEventListener('dragover', e => {
        e.preventDefault();
        uploadZone.classList.add('dragover');
    });

    uploadZone.addEventListener('dragleave', () => {
        uploadZone.classList.remove('dragover');
    });

    uploadZone.addEventListener('drop', e => {
        e.preventDefault();
        uploadZone.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file) handleFile(file);
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files[0]) handleFile(fileInput.files[0]);
    });

    function handleFile(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            alert('Seuls les fichiers PDF sont acceptés.');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            alert('Fichier trop volumineux (max 5 Mo).');
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        uploadZone.style.display = 'none';
        fileInfo.style.display = 'flex';
        updatePayBtn();
    }

    fileRemove.addEventListener('click', () => {
        selectedFile = null;
        fileInput.value = '';
        uploadZone.style.display = '';
        fileInfo.style.display = 'none';
        updatePayBtn();
    });

    // ─── Optional uploads (diploma + letter) ────────────────────
    function setupOptionalUpload(btnId, inputId, infoId, nameId, removeId, setter) {
        const btn = document.getElementById(btnId);
        const input = document.getElementById(inputId);
        const info = document.getElementById(infoId);
        const name = document.getElementById(nameId);
        const remove = document.getElementById(removeId);

        if (!btn) return;

        btn.addEventListener('click', () => input.click());

        input.addEventListener('change', () => {
            const file = input.files[0];
            if (!file) return;
            if (!file.name.toLowerCase().endsWith('.pdf')) {
                alert('Seuls les fichiers PDF sont acceptés.');
                return;
            }
            if (file.size > 5 * 1024 * 1024) {
                alert('Fichier trop volumineux (max 5 Mo).');
                return;
            }
            setter(file);
            name.textContent = file.name;
            btn.classList.add('has-file');
            info.style.display = 'flex';
        });

        remove.addEventListener('click', () => {
            setter(null);
            input.value = '';
            btn.classList.remove('has-file');
            info.style.display = 'none';
        });
    }

    setupOptionalUpload(
        'add-diploma-btn', 'diploma-file', 'diploma-info', 'diploma-name', 'diploma-remove',
        f => { diplomaFile = f; }
    );
    setupOptionalUpload(
        'add-letter-btn', 'letter-file', 'letter-info', 'letter-name', 'letter-remove',
        f => { letterFile = f; }
    );

    // ─── Access Flow ────────────────────────────────────────────
    payBtn.addEventListener('click', async () => {
        if (!selectedFile || !emailInput.value.includes('@')) return;

        payBtn.disabled = true;
        payBtn.textContent = 'Envoi en cours...';

        try {
            const formData = new FormData();
            formData.append('file', selectedFile);
            formData.append('email', emailInput.value);
            if (diplomaFile) formData.append('diploma', diplomaFile);
            if (letterFile) formData.append('letter', letterFile);

            const uploadRes = await fetch('/api/upload-cv', {
                method: 'POST',
                body: formData,
            });

            if (!uploadRes.ok) {
                const err = await uploadRes.json();
                throw new Error(err.detail || 'Erreur upload');
            }

            const { token } = await uploadRes.json();
            window.location.href = `/dashboard?token=${token}`;

        } catch (err) {
            alert('Erreur: ' + err.message);
            payBtn.disabled = false;
            payBtn.textContent = 'Accéder au dashboard \u2192';
        }
    });
});

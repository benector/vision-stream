const btn = document.getElementById('btn-toggle-stream');
const hub = document.getElementById('hub-cart');
const video = document.getElementById('main-video');
const panel = document.getElementById('side-panel');

// Variável global para controlar estado do stream
let isStreamActive = false;

// Alterna entre ativar e desativar o VisionStream
async function toggleStream() {
    isStreamActive = !isStreamActive;

    // Atualiza o visual do botão
    if (isStreamActive) {
        btn.innerText = "VISIONSTREAM ATIVO";
        btn.style.backgroundColor = "#2ed573";
    } else {
        btn.innerText = "ATIVAR VISIONSTREAM";
        btn.style.backgroundColor = "#ff4757";
    }

    // Chama rota do backend para ativar/desativar detecção
    const rota = isStreamActive ? 'activate' : 'deactivate';
    try {
        const response = await fetch(`/${rota}`);
        if (!response.ok) throw new Error("Erro na resposta do servidor");
        const data = await response.json();
        console.log("Python confirmou:", data.status);
    } catch (error) {
        console.error("Falha ao avisar o Python:", error);
    }
}

// Histórico e controle de categorias detectadas
let detectedCategories = new Map();
let productsHistory = [];

// Atualiza informações de detecção a cada segundo
setInterval(async () => {
    if (!isStreamActive) return;

    try {
        const response = await fetch('/get_info');
        const data = await response.json();
        const log = document.getElementById('metadata-log');
        const newEntry = document.createElement('p');
        const time = new Date().toLocaleTimeString();

        if (data && data.label && data.label !== "None") {
            // Exibe metadados do produto detectado
            newEntry.style.color = "#00ff00";
            newEntry.innerText = `[${time}] TIMESTAMP: ${data.timestamp || 'SYNC'} | DETECTED: ${data.label.toUpperCase()} | SCORE: ${data.score || 'N/A'} | ID: ${data.item_id || data.id}`;
        } else {
            // Exibe mensagem de nenhum objeto detectado
            newEntry.style.color = "#888";
            newEntry.innerText = `[${time}] STATUS: Nenhum objeto detectado no frame...`;
        }
        log.prepend(newEntry);

        if (!data || !data.label) return;

        hub.style.display = "block";

        // Armazena detecção nova no histórico
        if (!productsHistory.find(p => p.id === data.id)) {
            productsHistory.push(data);
        }

        // Atualiza categorias detectadas
        if (!detectedCategories.has(data.label)) {
            detectedCategories.set(data.label, []);
        }
        if (!detectedCategories.get(data.label).includes(data.id)) {
            detectedCategories.get(data.label).push(data.id);
            renderCategories();
            document.getElementById('label-count').innerText = detectedCategories.size;
        }
    } catch (error) {
        console.error("Erro ao buscar dados do YOLO:", error);
    }
}, 1000);

// Abre o painel lateral
function openPanel() {
    panel.classList.add('open');
}

// Fecha o painel lateral e retoma vídeo
function closePanel() {
    panel.classList.remove('open');
    video.play();
}

// Banco de dados global para armazenar categorias e IDs detectados
window.detectedDataStore = {};
window.currentViewId = null;

// Renderiza lista de categorias detectadas no painel
function renderCategories() {
    const list = document.getElementById('category-list');
    list.innerHTML = "";

    detectedCategories.forEach((ids, label) => {
        const storageKey = "cat_" + label;
        window.detectedDataStore[storageKey] = ids;

        const div = document.createElement('div');
        div.className = 'cat-item';
        div.onclick = () => showCategoryDetail(label, storageKey);
        div.innerHTML = `<span>${label.toUpperCase()}</span> →`;
        list.appendChild(div);
    });
}

// Exibe detalhes de uma categoria ou produto selecionado
function showCategoryDetail(label, storageKey, forceId = null) {
    const ids = window.detectedDataStore[storageKey];
    if (!ids) return;

    const lastItemId = ids[ids.length - 1];
    const itemData = productsHistory.find(i => i.id === lastItemId);
    if (!itemData) return;

    window.currentViewId = forceId || itemData.best_match_id;
    let productInCatalog = itemData.related.find(p => p.id === window.currentViewId) || itemData.related[0];
    const isOriginalMatch = (productInCatalog.id === itemData.best_match_id);

    // Renderiza produtos relacionados
    let relatedHTML = "";
    itemData.related.forEach((p) => {
        if (p.id !== productInCatalog.id) {
            const isAISelection = (p.id === itemData.best_match_id);
            relatedHTML += `
                <div class="rel-item"
                     style="padding:10px; border: 1px solid ${isAISelection ? '#2ed573' : '#eee'}; margin-top:10px; cursor:pointer; border-radius:10px;"
                     onclick="event.stopPropagation(); showCategoryDetail('${label}', '${storageKey}', '${p.id}')">

                    <img src=${p.img_base64 
                        ? `data:image/jpeg;base64,${p.img_base64}` 
                        : p.img_url}
                        referrerpolicy="no-referrer"
                        style="width:100px; border-radius:6px">

                    <div style="display:flex; flex-direction:column;gap:2px">
                        <span style="font-size:12px; font-weight:bold;">${p.name}</span>
                        ${isAISelection ? '<div style="text-align:center;color:#2ed573;border:1px solid #2ed573;font-size:10px;border-radius:10px;padding:5px;width:50px">MELHOR MATCH</div>' : ''}
                        <span style="color:#2ed573;font-size:11px;">${p.price}</span>
                    </div>
                </div>`;
        }
    });

    const content = document.getElementById('detail-content');
    document.getElementById('view-categories').style.display = 'none';
    document.getElementById('view-detail').style.display = 'block';

    // Scroll do painel para o topo
    const sidePanel = document.getElementById('side-panel');
    sidePanel.scrollTop = 0;

    // Renderiza produto principal e relacionados
    content.innerHTML = `
        <div class="product-highlight" style="border:2px solid ${isOriginalMatch ? '#2ed573' : '#ddd'}; padding:15px; border-radius:12px; background:#fff;">
            <small style="color:${isOriginalMatch ? '#27ae60' : '#12193b'}; font-weight:bold; display:block; margin-bottom:10px;">
                ${isOriginalMatch ? 'PRODUTO IDENTIFICADO' : 'OPÇÃO SEMELHANTE ENCONTRADA'}
            </small>

            <div style="display:flex; flex-direction:column; gap:10px; margin-bottom:15px;">
                <div style="flex:1; text-align:center;">
                    <img src=${productInCatalog.img_base64 
                        ? `data:image/jpeg;base64,${productInCatalog.img_base64}` 
                        : productInCatalog.img_url}
                        referrerpolicy="no-referrer" 
                        style="width:100%; height:150px; object-fit:cover; border-radius:6px; border:1px solid ${isOriginalMatch ? '#2ed573' : '#ddd'};">
                </div>
            </div>

            <h3 style="margin:0; color:#191970; font-size:15px;">${productInCatalog.name}</h3>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
                <span style="font-size:20px; color:#2ed573; font-weight:bold;">${productInCatalog.price}</span>
                <img style="width:60px;" src="https://api.qrserver.com/v1/create-qr-code/?size=100x100&data=${productInCatalog.url_produto}">
            </div>

            <div style="flex:1; flex-direction:row; text-align:left;">
                <small style="font-size:12px; color:#494848; display:block;">BUSCADO NA CENA:</small>
                <img src="data:image/jpeg;base64,${itemData.crop}" style="width:50%; height:80px; object-fit:cover; border-radius:6px; border:1px solid #ddd;">
            </div>
        </div>

        <div style="margin-top:20px; font-weight:bold; color:white; font-size:11px;">VEJA TAMBÉM:</div>
        <div class="related-list">${relatedHTML}</div>
    `;
}

// Volta para a visão de categorias
function showCategories() {
    document.getElementById('view-categories').style.display = 'block';
    document.getElementById('view-detail').style.display = 'none';
}

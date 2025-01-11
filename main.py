import os
import time
import concurrent.futures
from dotenv import load_dotenv
import streamlit as st
from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_text_splitters.character import CharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain.memory import ConversationBufferMemory
from langchain.chains import ConversationalRetrievalChain
from docx import Document  # For DOCX files
import pythoncom
from pptx import Presentation  # For PowerPoint files

# Load environment variables
load_dotenv()

# Corrected file path to use __file__
working_dir = os.path.dirname(os.path.abspath(__file__))

# Define CustomDocument class
class CustomDocument:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}

# Function to load documents based on file type (PDF, Word, PowerPoint, Text)
def load_document(file_path):
    file_extension = file_path.split('.')[-1].lower()

    # Process file based on its type
    if file_extension == 'pdf':
        loader = UnstructuredPDFLoader(file_path)
        raw_documents = loader.load()
    elif file_extension == 'docx':
        raw_documents = load_word(file_path)
    elif file_extension == 'pptx':
        raw_documents = load_ppt(file_path)
    elif file_extension == 'txt':
        raw_documents = load_txt(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_extension}")

    # Convert raw documents to CustomDocument objects
    documents = []
    for text in raw_documents:
        if isinstance(text, str):
            documents.append(CustomDocument(text))
        elif isinstance(text, dict):
            documents.append(CustomDocument(text.get('page_content', '')))
        else:
            documents.append(CustomDocument(str(text)))
    return documents

# Function to load text from Word (DOCX)
def load_word(file_path):
    doc = Document(file_path)
    text = []
    for paragraph in doc.paragraphs:
        text.append(paragraph.text)
    return text

# Function to load text from PowerPoint (PPTX)
def load_ppt(file_path):
    pythoncom.CoInitialize()  # Initialize COM
    presentation = Presentation(file_path)
    text = []
    for slide in presentation.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                text.append(shape.text)
    return text

# Function to load text from plain Text files (TXT)
def load_txt(file_path):
    with open(file_path, 'r') as f:
        text = f.readlines()
    return text

# Function to chunk documents with optimized parameters
def chunk_document(doc, text_splitter):
    """Split documents into chunks."""
    return text_splitter.split_documents([doc])

# Function to set up the vector store with more refined chunking
def setup_vectorstore(documents):
    embeddings = HuggingFaceEmbeddings()
    text_splitter = CharacterTextSplitter(
        separator="\n",  # Split documents by newlines
        chunk_size=1500,  # Larger chunk size to capture more context
        chunk_overlap=300  # Larger overlap to retain context across chunks
    )

    # Parallel processing of document chunks
    with concurrent.futures.ThreadPoolExecutor() as executor:
        doc_chunks = list(executor.map(lambda doc: chunk_document(doc, text_splitter), documents))

    # Flatten the list of chunks
    flattened_chunks = [chunk for sublist in doc_chunks for chunk in sublist]
    vectorstore = FAISS.from_documents(flattened_chunks, embeddings)
    return vectorstore

# Create the conversational chain with memory and retriever
def create_chain(vectorstore):
    llm = ChatGroq(
        model="llama-3.3-70b-versatile",  # Use larger model with better context understanding
        temperature=0.2
    )
    retriever = vectorstore.as_retriever()
    memory = ConversationBufferMemory(
        llm=llm,
        output_key="answer",
        memory_key="chat_history",
        return_messages=True
    )
    chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=retriever,
        chain_type="map_reduce",  # Use "map_reduce" for improved aggregation
        memory=memory,
        verbose=True
    )
    return chain

# Set up Streamlit page
st.set_page_config(
    page_title="Chat with Doc",
    page_icon="📄",
    layout="centered"
)

st.markdown("""
<div style="text-align: center;">
    <h1>Welcome to SmartDOC 📄</h1>
    <h5><i>Transform Your Documents into Intelligent Conversations 💬</i></h5>
</div>
""", unsafe_allow_html=True)

with st.expander("**About this app**"):
    st.write("""
        - Leverages the LLAMA 3.3 70b-versatile model to quickly transform documents (PDF, Word, PPT, Text) into interactive conversations. 
        - Extract insights and get precise answers based on the document’s content.
        - Save time with context-specific responses without reading everything.
        - Provides fast and accurate answers in real-time.
    """)

# Initialize chat history in Streamlit session state
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# File upload for multiple documents (PDF, DOCX, PPTX, TXT)
uploaded_files = st.file_uploader(label="Upload your documents", type=["pdf", "docx", "pptx", "txt"], accept_multiple_files=True)

if uploaded_files:
    # Save files to disk
    file_paths = []
    for uploaded_file in uploaded_files:
        file_path = os.path.join(working_dir, uploaded_file.name)
        file_paths.append(file_path)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

    # Show loading spinner while the documents are being processed
    with st.spinner("Processing documents... This may take a while."):
        start_time = time.time()

        # Load and process all documents
        all_documents = []
        for file_path in file_paths:
            all_documents.extend(load_document(file_path))

        # Setup vector store and conversation chain
        if "vectorstore" not in st.session_state:
            st.session_state.vectorstore = setup_vectorstore(all_documents)

        if "conversation_chain" not in st.session_state:
            st.session_state.conversation_chain = create_chain(st.session_state.vectorstore)

        # Log the processing time
        end_time = time.time()
        st.success(f"Documents processed in {end_time - start_time:.2f} seconds")

# Display chat history
for message in st.session_state.chat_history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handling user inputs (queries)
user_input = st.chat_input("Ask SmartDOC...")

if user_input:
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    # Manage long user inputs by splitting them into smaller chunks
    if len(user_input.split()) > 200:
        query_chunks = [user_input[i:i + 200] for i in range(0, len(user_input), 200)]
        full_answer = ""
        for chunk in query_chunks:
            response = st.session_state.conversation_chain({"question": chunk})
            full_answer += response["answer"] + " "  # Aggregate the answers
        assistant_response = full_answer.strip()
    else:
        response = st.session_state.conversation_chain({"question": user_input})
        assistant_response = response["answer"]

    with st.chat_message("assistant"):
        st.markdown(assistant_response)
        st.session_state.chat_history.append({"role": "assistant", "content": assistant_response})

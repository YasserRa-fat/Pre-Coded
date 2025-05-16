import React from 'react';
import { Route, Routes } from 'react-router-dom';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';

import LandingPage from './components/LandingPage';
import Login from './components/Login';
import Navbar from './components/Navbar';
import Register from './components/Register';

import CreateUserModel from './components/CreateUserModel';
import ModelDetail from './components/ModelDetail';
import ModelDiagram from './components/ModelDiagram';
import ModelFileDetail from './components/ModelFileDetail';
import ModelFilesList from './components/ModelFilesList';
import ModelPaste from './components/ModelPaste';
import UserModels from './components/UserModels';

import AppDetail from './components/AppDetail';
import ProjectDetail from './components/ProjectDetail';
import ProjectList from './components/ProjectList';

import ViewFileDetail from './components/ViewFileDetail';
import ViewFileDiagram from './components/ViewFileDiagram';
import ViewFilePaste from './components/ViewFilePaste';

import FormFileDetail from './components/FormFileDetail';
import FormFileDiagram from './components/FormFileDiagram';
import FormFilePaste from './components/FormFilePaste';

import FileDetail from './components/FileDetail';
import MediaFilesPage from './components/MediaFilesPage';
import PreviewPage from './components/PreviewPage';
import StaticFilesPage from './components/StaticFilesPage';
import TemplateFilesPage from './components/TemplateFilesPage';
function App() {
  return (
    <>
      <Navbar />

      <Routes>
        {/* Public */}
        <Route path="/" element={<LandingPage />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />

        {/* User‐model builder */}
        <Route path="/create-user-model" element={<CreateUserModel />} />
        <Route path="/user-models" element={<UserModels />} />
        <Route path="/usermodel/:id" element={<ModelDetail />} />
        <Route path="/parse-model" element={<ModelPaste />} />
        <Route path="/model-diagram/:fileId" element={<ModelDiagram />} />

        {/* Projects & Apps */}
        <Route path="/my-projects" element={<ProjectList />} />
        <Route path="/projects/:projectId" element={<ProjectDetail />} />
        <Route path="/projects/:projectId/preview" element={<PreviewPage />} />
        <Route path="/projects/:projectId/apps/:appId" element={<AppDetail />} />

        {/* Model files */}
        <Route
          path="/projects/:projectId/models/:modelId"
          element={<ModelFilesList />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/model-files/:fileId"
          element={<ModelFileDetail />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/model-diagram/:fileId"
          element={<ModelDiagram />}
        />

        {/* View‐file parsing */}
        <Route path="/parse-view" element={<ViewFilePaste />} />
        <Route path="/view-diagram/:fileId?" element={<ViewFileDiagram />} />
        <Route
          path="/projects/:projectId/apps/:appId/view-files/:fileId"
          element={<ViewFileDetail />}
        />

        {/* Form‐file parsing */}
        <Route path="/parse-form" element={<FormFilePaste />} />
        <Route path="/form-diagram/:fileId?" element={<FormFileDiagram />} />
        <Route
          path="/projects/:projectId/apps/:appId/form-files/:fileId"
          element={<FormFileDetail />}
        />

        {/* Generic file editors */}
        <Route
          path="/projects/:projectId/settings-files/:fileId"
          element={
            <FileDetail
              apiBase="settings-files"
              displayPathPrefix="settings.py"
            />
          }
        />
        <Route
          path="/projects/:projectId/url-files/:fileId"
          element={
            <FileDetail apiBase="url-files" displayPathPrefix="urls.py" />
          }
        />
        <Route
          path="/projects/:projectId/apps/:appId/:fileType/:fileId"
          element={<FileDetail />}
        />
        <Route
          path="/projects/:projectId/project-files/:fileId"
          element={<FileDetail apiBase="project-files" />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/app-files/:fileId"
          element={<FileDetail apiBase="app-files" displayPathPrefix="app" />}
        />

        {/* Static files */}
        <Route
          path="/projects/:projectId/static-files"
          element={<StaticFilesPage fileType="static" isApp={false} />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/static-files"
          element={<StaticFilesPage fileType="static" isApp={true} />}
        />
        <Route
          path="/apps/:appId/static-files"
          element={<StaticFilesPage fileType="static" isApp={true} />}
        />

        {/* Media files */}
        <Route
          path="/projects/:projectId/media-files"
          element={<MediaFilesPage isApp={false} />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/media-files"
          element={<MediaFilesPage isApp={true} />}
        />
        <Route
          path="/apps/:appId/media-files"
          element={<MediaFilesPage isApp={true} />}
        />

        {/* Template files */}
        <Route
          path="/projects/:projectId/template-files"
          element={<TemplateFilesPage isApp={false} />}
        />
        <Route
          path="/projects/:projectId/apps/:appId/template-files"
          element={<TemplateFilesPage isApp={true} />}
        />
        <Route
          path="/apps/:appId/template-files"
          element={<TemplateFilesPage isApp={true} />}
        />

        {/* Fallback */}
        <Route path="*" element={<div>Not Found</div>} />
      </Routes>

      {/* <FloatingChat /> */}
      <ToastContainer />
    </>
  );
}

export default App;

const Dashboard = () => {
    const [models, setModels] = useState([]);

    useEffect(() => {
        const fetchModels = async () => {
            const token = localStorage.getItem('access_token');
            const response = await axios.get('/api/user-models/', {
                headers: { Authorization: `Bearer ${token}` },
            });
            setModels(response.data);
        };

        fetchModels();
    }, []);

    return (
        <div>
            <h2>Your Models</h2>
            <table>
                <thead>
                    <tr>
                        <th>Model Name</th>
                        <th>Visibility</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {models.map(model => (
                        <tr key={model.id}>
                            <td>{model.model_name}</td>
                            <td>{model.visibility}</td>
                            <td>
                                <button onClick={() => {/* Edit Logic */}}>Edit</button>
                                <button onClick={() => {/* Delete Logic */}}>Delete</button>
                                <button onClick={() => {/* Generate API Logic */}}>Generate API</button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

// Scripted REST resource: GET /api/x_mcp_poc/identity/me.
// Require authentication at the API AND resource levels. Do not run as admin.
// Reject guests/inactive users even if a resource was accidentally misconfigured.
(function process(request, response) {
    var user = gs.getUser();
    if (!gs.isLoggedIn() || user.getName() === 'guest') {
        response.setStatus(401);
        return;
    }
    // Read only the caller's active flag; expose no user-table data.
    var caller = new GlideRecord('sys_user');
    if (!caller.get(user.getID()) ||
            (caller.getValue('active') !== '1' && caller.getValue('active') !== 'true')) {
        response.setStatus(401);
        return;
    }
    response.setHeader('Cache-Control', 'no-store');
    response.setBody({
        sys_id: user.getID(), user_name: user.getName()
    });
})(request, response);

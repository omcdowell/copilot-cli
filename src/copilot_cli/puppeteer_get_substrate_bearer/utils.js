function getArguments() {
    const args = process.argv.slice(2);

    if (args.length < 1) {
        console.error(
            "Too few arguments. Provide the username as: 'user=<your_user>' " +
            "(optional: debugMode=true). Sign in interactively in the Edge window; passwords are not accepted."
        );
        process.exit(1);
    }
    const user = getSingleArgument(args, "user");
    const debugMode = getOptionalArgument(args, "debugMode", "false");

    return {
        "user": user,
        "debugMode": debugMode
    };
}

function getSingleArgument(args, argumentName) {
    const argNameToSearch = `${argumentName}=`;

    const arg = args.filter(a => a.includes(argNameToSearch));
    if (arg.length === 0) {
        console.error(`Argument ${argumentName} not found`);
        process.exit(1);
    }
    return arg[0].split("=").slice(1).join("=");
}

function getOptionalArgument(args, argumentName, defaultValue) {
    const argNameToSearch = `${argumentName}=`;
    const arg = args.filter(a => a.includes(argNameToSearch));
    if (arg.length === 0) {
        return defaultValue;
    }
    return arg[0].split("=").slice(1).join("=");
}

module.exports = {
    getArguments
};
